"""OS-facing backend for VibeStack's authenticated automation API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import shlex
import signal
import stat
import struct
import subprocess
import sys
import threading
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

COMMON_ROOT = os.environ.get(
    "VIBESTACK_COMMON_ROOT",
    str(Path(__file__).resolve().parent.parent / "common"),
)
if COMMON_ROOT not in sys.path:
    sys.path.insert(0, COMMON_ROOT)
from vibestack_auth import ClientAuthError, WorkspaceClientStore  # noqa: E402

from files import DesktopFileStore, FileError, FileValue, MAX_FILE_BYTES
from runner import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_PAGE_BYTES,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    QUEUE_CAPACITY,
    WORKER_COUNT,
    CommandRunner,
    CommandSpec,
    RunnerError,
)
from sshkeys import SSHKeyError, SSHKeyStore


API_PREFIX = "/api/v1/automation"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7997
DEFAULT_HOME = "/home/vibe"
DEFAULT_DESKTOP_ROOT = "/home/vibe/Desktop"
DEFAULT_PROJECTS_ROOT = "/projects"
DEFAULT_TOKEN_FILE = "/home/vibe/.vibestack/automation.token"
DEFAULT_JOB_DIRECTORY = "/home/vibe/.vibestack/automation/jobs"
DEFAULT_AUDIT_LOG = "/data/logs/vibestack/automation-audit.jsonl"
DEFAULT_SESSION_ENV_FILE = "/run/vibestack/session.env"
DEFAULT_XDG_RUNTIME_DIR = "/run/vibestack/runtime"

BASH = "/bin/bash"
SCROT = "/usr/bin/scrot"
WMCTRL = "/usr/bin/wmctrl"
XDOTOOL = "/usr/bin/xdotool"
XPROP = "/usr/bin/xprop"
XCLIP = "/usr/bin/xclip"

MAX_JSON_BODY_BYTES = 1024 * 1024 + 4096
MAX_CLIPBOARD_BYTES = 1024 * 1024
MAX_COMMAND_ARGS = 256
MAX_ARGUMENT_BYTES = 64 * 1024
MAX_SHELL_BYTES = 256 * 1024
MAX_ENVIRONMENT_ENTRIES = 64
MAX_ENVIRONMENT_BYTES = 64 * 1024
MAX_TOOL_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_SCREENSHOT_BYTES = MAX_FILE_BYTES
MAX_AUDIT_BYTES = 10 * 1024 * 1024
AUDIT_BACKUPS = 3
MAX_WINDOWS = 256
WINDOW_OPERATION_TIMEOUT_SECONDS = 15.0
WINDOW_LIST_ATTEMPTS = 3
WINDOW_LIST_RETRY_SECONDS = 0.05
APPLICATION_LAUNCH_PENDING_SECONDS = 10.0
APPLICATION_STOP_GRACE_SECONDS = 2.0
WINDOW_STATES = ("minimized", "maximized", "normal")
JOB_TERMINAL_AUDIT_STATUSES = {
    "succeeded": 200,
    "cancelled": 499,
    "timed_out": 504,
    "failed": 500,
    "interrupted": 503,
}
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
APP_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
XID_RE = re.compile(r"^0x[0-9a-fA-F]{1,16}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

PROTECTED_ENVIRONMENT = frozenset(
    {
        "DISPLAY",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "PATH",
        "XDG_RUNTIME_DIR",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "XDG_DATA_DIRS",
        "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_TYPE",
        "DBUS_SESSION_BUS_ADDRESS",
        "GNOME_KEYRING_CONTROL",
        "XAUTHORITY",
    }
)
SESSION_ENVIRONMENT_KEYS = frozenset(
    {
        "DBUS_SESSION_BUS_ADDRESS",
        "GNOME_KEYRING_CONTROL",
        "XAUTHORITY",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "XDG_DATA_DIRS",
    }
)


class AutomationError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class TokenProvider:
    """Read a rotatable bearer token without ever retaining it in logs."""

    def __init__(
        self,
        token_file: str = DEFAULT_TOKEN_FILE,
        token: str | None = None,
        client_store: WorkspaceClientStore | None = None,
    ):
        self.token_file = token_file
        self._fixed_token = token
        self.client_store = client_store or WorkspaceClientStore()
        self._allow_clients = token is None or client_store is not None

    def authenticate(self, authorization: str | None) -> bool:
        expected = self._fixed_token if self._fixed_token is not None else self._read()
        supplied = ""
        if authorization is not None and len(authorization) <= 1024:
            scheme, separator, value = authorization.partition(" ")
            if separator and scheme.lower() == "bearer":
                supplied = value.strip()
        # compare_digest is invoked for every syntactically parseable or
        # malformed credential once the server has a token.
        supplied_digest = hashlib.sha256(supplied.encode("utf-8")).digest()
        expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
        legacy_match = hmac.compare_digest(supplied_digest, expected_digest)
        return legacy_match or (
            self._allow_clients
            and bool(supplied)
            and self.client_store.authenticate(supplied)
        )

    def _read(self) -> str:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.token_file, flags)
        except OSError as exc:
            raise AutomationError(
                "authentication_unavailable",
                "Automation authentication is not configured.",
                503,
            ) from exc
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_size > 1024
            ):
                raise AutomationError(
                    "authentication_unavailable",
                    "The automation token failed a safety check.",
                    503,
                )
            raw = os.read(fd, 1025)
        finally:
            os.close(fd)
        try:
            token = raw.decode("ascii").strip()
        except UnicodeDecodeError:
            token = ""
        if len(token) < 32 or len(token) > 512 or any(character.isspace() for character in token):
            raise AutomationError(
                "authentication_unavailable",
                "The automation token is invalid.",
                503,
            )
        return token


class AuditLogger:
    """Append bounded metadata-only JSON records to the shared audit log."""

    def __init__(self, path: str = DEFAULT_AUDIT_LOG):
        self.path = path
        self._lock = threading.Lock()

    def record(
        self,
        *,
        request_id: str,
        method: str,
        action: str,
        status: int,
        duration_ms: int,
        details: Mapping[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "timestamp": _utc_now(),
            "request_id": request_id,
            "service": "automation",
            "method": method
            if re.fullmatch(r"[A-Z][A-Z0-9_-]{0,31}", method)
            else "OTHER",
            "action": action,
            "status": status,
            "duration_ms": max(0, min(duration_ms, 24 * 60 * 60 * 1000)),
        }
        if details:
            # Callers pass bounded counts, generated IDs, safe target
            # identifiers/paths, and boolean outcomes only—never contents.
            payload["details"] = dict(details)
        body = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if len(body) > 8192:
            return
        try:
            parent = os.path.dirname(self.path)
            os.makedirs(parent, mode=0o700, exist_ok=True)
            with self._lock:
                fd = self._open_audit()
                try:
                    info = os.fstat(fd)
                    if not self._safe_info(info):
                        return
                    if info.st_size + len(body) > MAX_AUDIT_BYTES:
                        os.close(fd)
                        fd = -1
                        if not self._rotate():
                            return
                        fd = self._open_audit()
                        if not self._safe_info(os.fstat(fd)):
                            return
                    view = memoryview(body)
                    offset = 0
                    while offset < len(view):
                        offset += os.write(fd, view[offset:])
                finally:
                    if fd >= 0:
                        os.close(fd)
        except OSError:
            # Logging must not turn an otherwise safe API operation into an
            # outage. Supervisor stderr still reports service-level failures.
            return

    def _open_audit(self) -> int:
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o640)
        os.fchmod(fd, 0o640)
        return fd

    @staticmethod
    def _safe_info(info: os.stat_result) -> bool:
        return (
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and info.st_nlink == 1
        )

    def _rotate(self) -> bool:
        """Rotate exact, validated sibling paths while holding ``_lock``."""

        try:
            current_info = os.lstat(self.path)
        except FileNotFoundError:
            return True
        if not self._safe_info(current_info) or stat.S_ISLNK(current_info.st_mode):
            return False
        for index in range(AUDIT_BACKUPS - 1, 0, -1):
            source = "%s.%d" % (self.path, index)
            target = "%s.%d" % (self.path, index + 1)
            try:
                source_info = os.lstat(source)
            except FileNotFoundError:
                continue
            if not self._safe_info(source_info) or stat.S_ISLNK(source_info.st_mode):
                return False
            try:
                target_info = os.lstat(target)
            except FileNotFoundError:
                pass
            else:
                if not self._safe_info(target_info) or stat.S_ISLNK(target_info.st_mode):
                    return False
            os.replace(source, target)
        first = self.path + ".1"
        try:
            first_info = os.lstat(first)
        except FileNotFoundError:
            pass
        else:
            if not self._safe_info(first_info) or stat.S_ISLNK(first_info.st_mode):
                return False
        os.replace(self.path, first)
        return True


class DesktopEnvironment:
    def __init__(
        self,
        *,
        home: str = DEFAULT_HOME,
        session_env_file: str = DEFAULT_SESSION_ENV_FILE,
        xdg_runtime_dir: str = DEFAULT_XDG_RUNTIME_DIR,
    ):
        self.home = home
        self.session_env_file = session_env_file
        self.xdg_runtime_dir = xdg_runtime_dir

    def build(self, additions: object | None = None) -> dict[str, str]:
        environment = {
            "DISPLAY": ":0",
            "HOME": self.home,
            "USER": "vibe",
            "LOGNAME": "vibe",
            "SHELL": BASH,
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "XDG_RUNTIME_DIR": self.xdg_runtime_dir,
            "XDG_CURRENT_DESKTOP": "XFCE",
            "XDG_SESSION_TYPE": "x11",
        }
        environment.update(self._session_values())
        if additions is None:
            return environment
        if not isinstance(additions, dict) or len(additions) > MAX_ENVIRONMENT_ENTRIES:
            raise AutomationError(
                "invalid_environment", "env must be a small object of string values.", 400
            )
        total = 0
        for name, value in additions.items():
            if (
                not isinstance(name, str)
                or not ENV_NAME_RE.fullmatch(name)
                or name in PROTECTED_ENVIRONMENT
                or not isinstance(value, str)
                or "\x00" in value
            ):
                raise AutomationError(
                    "invalid_environment",
                    "env contains an invalid or protected entry.",
                    400,
                )
            total += len(name.encode("utf-8")) + len(value.encode("utf-8"))
            if total > MAX_ENVIRONMENT_BYTES:
                raise AutomationError(
                    "invalid_environment", "env exceeds the 64 KiB limit.", 400
                )
            environment[name] = value
        return environment

    def _session_values(self) -> dict[str, str]:
        try:
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.session_env_file, flags)
        except FileNotFoundError:
            return {}
        except OSError:
            return {}
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or info.st_size > 16 * 1024
                or stat.S_IMODE(info.st_mode) & 0o022
            ):
                return {}
            raw = os.read(fd, 16 * 1024 + 1)
        finally:
            os.close(fd)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        values: dict[str, str] = {}
        if isinstance(parsed, dict):
            candidates = parsed.items()
        else:
            shell_values: dict[str, str] = {}
            for line in text.splitlines():
                match = re.fullmatch(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)\s*", line)
                if not match:
                    continue
                try:
                    parts = shlex.split(match.group(2), posix=True)
                except ValueError:
                    continue
                if len(parts) == 1:
                    shell_values[match.group(1)] = parts[0]
            candidates = shell_values.items()
        for name, value in candidates:
            if (
                name in SESSION_ENVIRONMENT_KEYS
                and isinstance(value, str)
                and "\x00" not in value
                and len(value.encode("utf-8")) <= 4096
            ):
                values[name] = value
        return values


class AutomationBackend:
    def __init__(
        self,
        *,
        desktop_root: str = DEFAULT_DESKTOP_ROOT,
        projects_root: str = DEFAULT_PROJECTS_ROOT,
        source_project: str | None = None,
        job_directory: str = DEFAULT_JOB_DIRECTORY,
        session_env_file: str = DEFAULT_SESSION_ENV_FILE,
        applications_file: str | None = None,
        runner: CommandRunner | None = None,
        expected_uid: int | None = None,
        xdg_runtime_dir: str = DEFAULT_XDG_RUNTIME_DIR,
        client_store: WorkspaceClientStore | None = None,
        ssh_key_store: SSHKeyStore | None = None,
    ):
        self.files = DesktopFileStore(desktop_root, expected_uid=expected_uid)
        self.project_files = DesktopFileStore(
            projects_root, expected_uid=expected_uid,
            mounted_subroots=(source_project,) if source_project else (),
        )
        self.client_store = client_store or WorkspaceClientStore()
        self.ssh_keys = ssh_key_store or SSHKeyStore(os.path.dirname(desktop_root))
        self.environment = DesktopEnvironment(
            home=os.path.dirname(desktop_root),
            session_env_file=session_env_file,
            xdg_runtime_dir=xdg_runtime_dir,
        )
        self.runner = runner or CommandRunner(job_directory)
        self.applications_file = applications_file or str(
            Path(__file__).with_name("applications.json")
        )
        self._applications = self._load_applications()
        self._application_lock = threading.RLock()
        self._pending_applications: dict[
            str, tuple[subprocess.Popen[bytes], float]
        ] = {}
        self._clipboard_lock = threading.RLock()
        self._clipboard_process: subprocess.Popen[bytes] | None = None

    def close(self) -> None:
        with self._clipboard_lock:
            self._stop_clipboard_owner()
        # The command runner owns process groups that intentionally live in
        # separate sessions. Do not return from service shutdown until those
        # groups have received TERM/KILL cleanup and workers have converged.
        self.runner.shutdown(wait=True)

    def set_audit_logger(self, audit: AuditLogger) -> None:
        """Send redacted terminal job metadata to the shared audit stream."""

        def record_terminal(
            request_id: str, details: Mapping[str, object]
        ) -> None:
            job_status = details.get("status")
            status = JOB_TERMINAL_AUDIT_STATUSES.get(
                job_status if isinstance(job_status, str) else "", 500
            )
            audit.record(
                request_id=request_id,
                method="JOB",
                action="job.terminal",
                status=status,
                duration_ms=0,
                details=details,
            )

        self.runner.set_terminal_event_handler(record_terminal)

    def capabilities(self) -> dict[str, Any]:
        return {
            "api_version": "1",
            "base_path": API_PREFIX,
            "authentication": "bearer",
            "desktop": {"display": ":0", "file_root": "Desktop"},
            "project_workflows": {
                "default_root": "projects",
                "roots": {
                    "desktop": self.files.root,
                    "projects": self.project_files.root,
                },
            },
            "file_preconditions": {
                "api_writers": "serialized",
                "create_if_absent": "atomic",
                "external_replace": "best_effort_revalidation",
            },
            "allowlists": {
                "application_ids": [application["id"] for application in self._applications],
                "application_operations": ["start", "stop"],
                "window_states": list(WINDOW_STATES),
            },
            "limits": {
                "workers": WORKER_COUNT,
                "queued_jobs": QUEUE_CAPACITY,
                "timeout_seconds": {"min": MIN_TIMEOUT_SECONDS, "max": MAX_TIMEOUT_SECONDS},
                "output_bytes_per_stream": MAX_OUTPUT_BYTES,
                "output_page_bytes": MAX_OUTPUT_PAGE_BYTES,
                "file_bytes": MAX_FILE_BYTES,
                "clipboard_bytes": MAX_CLIPBOARD_BYTES,
                "screenshot_bytes": MAX_SCREENSHOT_BYTES,
            },
            "routes": {
                "commands": API_PREFIX + "/commands",
                "shell": API_PREFIX + "/shell",
                "jobs": API_PREFIX + "/jobs/{id}",
                "job_output": API_PREFIX + "/jobs/{id}/output",
                "job_cancel": API_PREFIX + "/jobs/{id}/cancel",
                "screenshot": API_PREFIX + "/screenshot",
                "applications": API_PREFIX + "/applications",
                "windows": API_PREFIX + "/windows",
                "clipboard": API_PREFIX + "/clipboard",
                "files": API_PREFIX + "/files/{path}",
                "project_files": API_PREFIX + "/projects/{path}",
                "pairing_request": API_PREFIX + "/pairing/requests",
                "pairing_poll": API_PREFIX + "/pairing/requests/{id}/poll",
                "ssh_keys": API_PREFIX + "/ssh-keys",
            },
        }

    def submit_command(
        self,
        body: dict[str, Any],
        *,
        shell: bool,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        expected = {"command", "cwd", "root", "env", "timeout_seconds"} if shell else {
            "argv",
            "cwd",
            "root",
            "env",
            "timeout_seconds",
        }
        unknown = set(body) - expected
        required = "command" if shell else "argv"
        if unknown or required not in body:
            raise AutomationError(
                "invalid_command",
                "The command request has missing or unknown fields.",
                400,
            )
        timeout_seconds = body.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not MIN_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TIMEOUT_SECONDS
        ):
            raise AutomationError(
                "invalid_timeout", "timeout_seconds must be between 1 and 300.", 400
            )
        root = body.get("root", "desktop")
        if root not in ("desktop", "projects"):
            raise AutomationError("invalid_root", "root must be desktop or projects.", 400)
        cwd = (self.files if root == "desktop" else self.project_files).require_cwd(body.get("cwd"))
        env = self.environment.build(body.get("env"))
        if shell:
            command = body["command"]
            if (
                not isinstance(command, str)
                or not command
                or "\x00" in command
                or len(command.encode("utf-8")) > MAX_SHELL_BYTES
            ):
                raise AutomationError(
                    "invalid_command", "command must be a non-empty string up to 256 KiB.", 400
                )
            argv = (BASH, "-lc", command)
            kind = "shell"
        else:
            argv = self._require_argv(body["argv"])
            kind = "command"
        job = self.runner.submit(
            CommandSpec(
                kind=kind,
                argv=tuple(argv),
                cwd=cwd,
                env=env,
                timeout_seconds=timeout_seconds,
                request_id=request_id,
            )
        )
        return {"job": job.public()}

    def request_pairing(self, body: dict[str, Any]) -> dict[str, Any]:
        if set(body) != {"device_label", "permissions"}:
            raise AutomationError(
                "invalid_pairing_request",
                "Pairing requires only device_label and permissions.",
                400,
            )
        try:
            return self.client_store.request_pairing(
                body["device_label"], body["permissions"]
            )
        except ClientAuthError as exc:
            raise AutomationError(exc.code, exc.message, exc.status) from None

    def poll_pairing(self, pairing_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if set(body) != {"polling_secret"}:
            raise AutomationError(
                "invalid_pairing_poll", "Pairing poll requires only polling_secret.", 400
            )
        try:
            return self.client_store.poll(pairing_id, body["polling_secret"])
        except ClientAuthError as exc:
            raise AutomationError(exc.code, exc.message, exc.status) from None

    def list_ssh_keys(self) -> dict[str, Any]:
        try:
            return self.ssh_keys.list()
        except SSHKeyError as exc:
            raise AutomationError(exc.code, exc.message, exc.status) from None

    def add_ssh_key(self, body: dict[str, Any]) -> dict[str, Any]:
        if set(body) != {"public_key"}:
            raise AutomationError("invalid_ssh_public_key", "SSH key creation requires only public_key.", 400)
        try:
            return self.ssh_keys.add(body["public_key"])
        except SSHKeyError as exc:
            raise AutomationError(exc.code, exc.message, exc.status) from None

    def remove_ssh_key(self, key_id: str) -> dict[str, Any]:
        try:
            return self.ssh_keys.remove(key_id)
        except SSHKeyError as exc:
            raise AutomationError(exc.code, exc.message, exc.status) from None

    @staticmethod
    def _require_argv(value: object) -> tuple[str, ...]:
        if not isinstance(value, list) or not 1 <= len(value) <= MAX_COMMAND_ARGS:
            raise AutomationError(
                "invalid_argv", "argv must contain between 1 and 256 strings.", 400
            )
        total = 0
        for item in value:
            if not isinstance(item, str) or not item or "\x00" in item:
                raise AutomationError("invalid_argv", "argv contains an invalid value.", 400)
            total += len(item.encode("utf-8"))
        if total > MAX_ARGUMENT_BYTES or not os.path.isabs(value[0]):
            raise AutomationError(
                "invalid_argv", "argv must use an absolute executable and fit within 64 KiB.", 400
            )
        if not os.path.isfile(value[0]) or not os.access(value[0], os.X_OK):
            raise AutomationError("executable_not_found", "The executable is unavailable.", 400)
        return tuple(value)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return {"job": self.runner.get(job_id).public()}

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return {"job": self.runner.cancel(job_id).public()}

    def job_output(
        self, job_id: str, stream: str, cursor: int, limit: int
    ) -> dict[str, Any]:
        page = self.runner.output_page(job_id, stream, cursor, limit)
        data = page.pop("data")
        assert isinstance(data, bytes)
        return {
            "job_id": job_id,
            "stream": stream,
            "data": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
            **page,
        }

    def screenshot(self, filename: object | None = None) -> tuple[bytes, FileValue | None]:
        if filename is not None:
            if not isinstance(filename, str) or not filename.lower().endswith(".png"):
                raise AutomationError(
                    "invalid_screenshot_filename",
                    "filename must be a Desktop-relative .png path.",
                    400,
                )
            filename = self.files.require_relative_path(filename)
        try:
            self._require_tool(SCROT)
            result = _run_bounded(
                # scrot's documented '-' output avoids reopening any
                # attacker-replaceable pathname between capture and validation.
                [SCROT, "--format", "png", "-"],
                env=self.environment.build(),
                timeout=15,
                output_limit=MAX_SCREENSHOT_BYTES,
            )
            if result.returncode != 0 or result.output_truncated:
                raise AutomationError("screenshot_failed", "The desktop screenshot failed.", 503)
            image = result.stdout
            _validate_png(image)
            stored = self.files.write(filename, image) if filename is not None else None
            return image, stored
        except subprocess.TimeoutExpired:
            raise AutomationError("screenshot_timeout", "The desktop screenshot timed out.", 504) from None

    def applications(self) -> dict[str, Any]:
        windows = self._windows()
        return {"applications": [self._application_payload(app, windows) for app in self._applications]}

    def start_application(self, app_id: str) -> dict[str, Any]:
        with self._application_lock:
            app = self._application(app_id)
            before = self._windows()
            payload = self._application_payload(app, before)
            if not payload["installed"]:
                raise AutomationError(
                    "application_not_installed",
                    "The catalog application is not installed.",
                    409,
                )
            if payload["running"]:
                self._pending_applications.pop(app_id, None)
                return {
                    "application": payload,
                    "started": False,
                    "already_running": True,
                    "launch_pending": False,
                }
            now = time.monotonic()
            pending = self._pending_applications.get(app_id)
            if pending is not None and pending[1] > now:
                return {
                    "application": payload,
                    "started": False,
                    "already_running": False,
                    "launch_pending": True,
                }
            self._pending_applications.pop(app_id, None)
            try:
                process = subprocess.Popen(
                    app["argv"],
                    cwd=self.files.root,
                    env=self.environment.build(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
            except OSError as exc:
                raise AutomationError(
                    "application_start_failed",
                    "The catalog application could not be started.",
                    503,
                ) from exc
            # GUI launchers commonly fork and exit before their first window
            # becomes visible, so use a short time lease rather than poll().
            self._pending_applications[app_id] = (
                process,
                now + APPLICATION_LAUNCH_PENDING_SECONDS,
            )
            return {
                "application": payload,
                "started": True,
                "already_running": False,
                "launch_pending": True,
            }

    def stop_application(self, app_id: str) -> dict[str, Any]:
        with self._application_lock:
            deadline = time.monotonic() + WINDOW_OPERATION_TIMEOUT_SECONDS
            app = self._application(app_id)
            windows = self._windows(deadline=deadline)
            matching = self._matching_windows(app, windows)
            close_requests = 0
            pending_cancelled = False
            if not matching:
                pending_cancelled = self._cancel_pending_application(
                    app_id, deadline
                )
            for window in matching:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AutomationError(
                        "application_stop_timeout",
                        "Closing application windows timed out.",
                        504,
                    )
                self._revalidate_window(
                    window["id"],
                    expected_class=window["wm_class"],
                    expected_pid=window["pid"],
                    timeout=remaining,
                )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AutomationError(
                        "application_stop_timeout",
                        "Closing application windows timed out.",
                        504,
                    )
                result = self._desktop_tool(
                    [WMCTRL, "-ic", window["id"]], timeout=remaining
                )
                if result.returncode != 0:
                    raise AutomationError(
                        "application_stop_failed",
                        "An application window could not be closed.",
                        503,
                    )
                close_requests += 1
            self._pending_applications.pop(app_id, None)
            return {
                "application": self._application_payload(app, windows),
                "stop_requested": bool(matching) or pending_cancelled,
                # WM_DELETE_WINDOW is asynchronous; this is deliberately a
                # request count, not an unverified claim that windows closed.
                "close_requests": close_requests,
                "pending_launch_cancelled": pending_cancelled,
            }

    def windows(self) -> dict[str, Any]:
        windows = self._windows()
        active = next((item["id"] for item in windows if item["active"]), None)
        return {"active_window": active, "windows": windows}

    def set_window_state(self, xid: str, state_name: object) -> dict[str, Any]:
        xid = _require_xid(xid)
        if state_name not in WINDOW_STATES:
            raise AutomationError(
                "invalid_window_state",
                "state must be minimized, maximized, or normal.",
                400,
            )
        original = next((window for window in self._windows() if window["id"] == xid), None)
        if original is None:
            raise AutomationError("window_not_found", "The desktop window does not exist.", 404)
        self._revalidate_window(
            xid,
            expected_class=original["wm_class"],
            expected_pid=original["pid"],
        )
        decimal_id = str(int(xid, 16))
        if state_name == "minimized":
            result = self._desktop_tool([XDOTOOL, "windowminimize", decimal_id])
        elif state_name == "maximized":
            self._desktop_tool([XDOTOOL, "windowmap", decimal_id])
            result = self._desktop_tool(
                [WMCTRL, "-ir", xid, "-b", "add,maximized_vert,maximized_horz"]
            )
        else:
            self._desktop_tool([XDOTOOL, "windowmap", decimal_id])
            result = self._desktop_tool(
                [WMCTRL, "-ir", xid, "-b", "remove,maximized_vert,maximized_horz"]
            )
        if result.returncode != 0:
            raise AutomationError("window_update_failed", "The window state update failed.", 503)
        deadline = time.monotonic() + 2.0
        current = dict(original)
        while True:
            properties = self._window_properties(
                xid, timeout=max(0.1, deadline - time.monotonic())
            )
            if (
                properties is None
                or properties["wm_class"] != original["wm_class"]
                or (
                    original["pid"] is not None
                    and properties["pid"] != original["pid"]
                )
            ):
                raise AutomationError(
                    "window_changed", "The window changed during the state update.", 409
                )
            current.update(
                wm_class=properties["wm_class"],
                pid=properties["pid"],
                state=properties["state"],
            )
            if properties["state"] == state_name:
                break
            if time.monotonic() >= deadline:
                raise AutomationError(
                    "window_state_timeout", "The requested window state was not reached.", 504
                )
            time.sleep(0.05)
        return {"window": current}

    def get_clipboard(self) -> bytes:
        self._require_tool(XCLIP)
        try:
            result = _run_bounded(
                [XCLIP, "-selection", "clipboard", "-out"],
                env=self.environment.build(),
                timeout=5,
                output_limit=MAX_CLIPBOARD_BYTES,
            )
        except subprocess.TimeoutExpired:
            raise AutomationError("clipboard_timeout", "The clipboard read timed out.", 504) from None
        if result.output_truncated:
            raise AutomationError(
                "clipboard_too_large", "The clipboard exceeds the 1 MiB limit.", 413
            )
        if result.returncode != 0:
            raise AutomationError("clipboard_unavailable", "The clipboard is unavailable.", 409)
        try:
            result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            raise AutomationError(
                "clipboard_not_text", "The clipboard does not contain UTF-8 text.", 409
            ) from None
        return result.stdout

    def set_clipboard(self, data: bytes) -> dict[str, Any]:
        if len(data) > MAX_CLIPBOARD_BYTES:
            raise AutomationError("clipboard_too_large", "Clipboard text exceeds 1 MiB.", 413)
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise AutomationError("invalid_clipboard", "Clipboard text must be UTF-8.", 400) from None
        self._require_tool(XCLIP)
        with self._clipboard_lock:
            self._stop_clipboard_owner()
            try:
                process = subprocess.Popen(
                    # Keep the owning process in the foreground so its PID and
                    # process group remain ours to replace.  xclip's default
                    # `-silent` mode daemonizes and exits immediately for an
                    # empty selection on Ubuntu 24.04.
                    [XCLIP, "-selection", "clipboard", "-in", "-quiet"],
                    env=self.environment.build(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
                assert process.stdin is not None
                write_error: list[BaseException] = []

                def write_selection() -> None:
                    try:
                        assert process.stdin is not None
                        process.stdin.write(data)
                        process.stdin.close()
                    except (OSError, BrokenPipeError) as exc:
                        write_error.append(exc)

                writer = threading.Thread(
                    target=write_selection,
                    name="automation-clipboard-writer",
                    daemon=True,
                )
                writer.start()
                writer.join(timeout=5)
                if writer.is_alive() or write_error:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    writer.join(timeout=1)
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                    raise AutomationError(
                        "clipboard_write_failed", "The clipboard write failed.", 503
                    )
            except AutomationError:
                raise
            except OSError as exc:
                try:
                    process.kill()  # type: ignore[possibly-undefined]
                except (NameError, OSError):
                    pass
                raise AutomationError("clipboard_write_failed", "The clipboard write failed.", 503) from exc
            time.sleep(0.02)
            if process.poll() is not None:
                raise AutomationError("clipboard_write_failed", "The clipboard write failed.", 503)
            self._clipboard_process = process
        return {"bytes": len(data)}

    def _stop_clipboard_owner(self) -> None:
        process = self._clipboard_process
        self._clipboard_process = None
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=1)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def _load_applications(self) -> list[dict[str, Any]]:
        try:
            raw = Path(self.applications_file).read_bytes()
            if len(raw) > 64 * 1024:
                raise ValueError("catalog too large")
            value = json.loads(raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise AutomationError(
                "application_catalog_invalid", "The fixed application catalog is invalid.", 503
            ) from exc
        if not isinstance(value, dict) or value.get("version") != 1:
            raise AutomationError(
                "application_catalog_invalid", "The fixed application catalog is invalid.", 503
            )
        applications = value.get("applications")
        if not isinstance(applications, list) or not applications:
            raise AutomationError(
                "application_catalog_invalid", "The fixed application catalog is invalid.", 503
            )
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for application in applications:
            if not isinstance(application, dict) or set(application) != {
                "id",
                "name",
                "argv",
                "requires",
                "wm_classes",
            }:
                raise AutomationError(
                    "application_catalog_invalid", "The fixed application catalog is invalid.", 503
                )
            app_id = application["id"]
            argv = application["argv"]
            requires = application["requires"]
            classes = application["wm_classes"]
            if (
                not isinstance(app_id, str)
                or not APP_ID_RE.fullmatch(app_id)
                or app_id in seen
                or not isinstance(application["name"], str)
                or not isinstance(argv, list)
                or not argv
                or not all(isinstance(arg, str) and arg and "\x00" not in arg for arg in argv)
                or not os.path.isabs(argv[0])
                or not isinstance(requires, list)
                or not all(isinstance(path, str) and os.path.isabs(path) for path in requires)
                or not isinstance(classes, list)
                or not classes
                or not all(isinstance(name, str) and 0 < len(name) <= 256 for name in classes)
            ):
                raise AutomationError(
                    "application_catalog_invalid", "The fixed application catalog is invalid.", 503
                )
            seen.add(app_id)
            normalized.append(application)
        return normalized

    def _application(self, app_id: str) -> dict[str, Any]:
        if not APP_ID_RE.fullmatch(app_id):
            raise AutomationError("application_not_found", "The catalog application does not exist.", 404)
        for application in self._applications:
            if application["id"] == app_id:
                return application
        raise AutomationError("application_not_found", "The catalog application does not exist.", 404)

    def _application_payload(
        self, app: dict[str, Any], windows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        matching = self._matching_windows(app, windows)
        installed = all(os.path.isfile(path) and os.access(path, os.X_OK) for path in app["requires"])
        return {
            "id": app["id"],
            "name": app["name"],
            "installed": installed,
            "running": bool(matching),
            "windows": [window["id"] for window in matching],
        }

    def _cancel_pending_application(self, app_id: str, deadline: float) -> bool:
        pending = self._pending_applications.get(app_id)
        if pending is None:
            return False
        process, lease_deadline = pending
        now = time.monotonic()
        if now >= lease_deadline:
            self._pending_applications.pop(app_id, None)
            return False
        # Reap an exited launcher first. Otherwise its zombie keeps the old
        # process group apparently alive and a detached GUI could be falsely
        # reported as cancelled even though it is outside that group.
        process.poll()
        if not self._application_group_exists(process.pid):
            # The fixed launcher may have detached before publishing a window.
            # Keep the lease so a retry cannot spawn another copy, and require
            # the caller to retry once the window either appears or times out.
            raise AutomationError(
                "application_launch_pending",
                "The application launch is pending and cannot yet be stopped safely.",
                409,
            )
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            raise AutomationError(
                "application_launch_pending",
                "The application launch is pending and cannot yet be stopped safely.",
                409,
            ) from None
        graceful_deadline = min(
            deadline, time.monotonic() + APPLICATION_STOP_GRACE_SECONDS
        )
        while True:
            process.poll()  # reap a terminated group leader before killpg(0)
            if not self._application_group_exists(process.pid):
                break
            if time.monotonic() >= graceful_deadline:
                break
            time.sleep(0.02)
        if self._application_group_exists(process.pid):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            while True:
                process.poll()
                if not self._application_group_exists(process.pid):
                    break
                if time.monotonic() >= deadline:
                    raise AutomationError(
                        "application_stop_timeout",
                        "Cancelling the pending application launch timed out.",
                        504,
                    )
                time.sleep(0.02)
        try:
            process.wait(timeout=0)
        except subprocess.TimeoutExpired:
            pass
        self._pending_applications.pop(app_id, None)
        return True

    @staticmethod
    def _application_group_exists(process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _matching_windows(
        app: dict[str, Any], windows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        classes = {value.lower() for value in app["wm_classes"]}
        return [window for window in windows if window["wm_class"].lower() in classes]

    def _windows(self, *, deadline: float | None = None) -> list[dict[str, Any]]:
        self._require_tool(WMCTRL)
        self._require_tool(XDOTOOL)
        self._require_tool(XPROP)
        if deadline is None:
            deadline = time.monotonic() + WINDOW_OPERATION_TIMEOUT_SECONDS
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AutomationError(
                "window_list_timeout", "Desktop window enumeration timed out.", 504
            )
        listing = None
        for attempt in range(WINDOW_LIST_ATTEMPTS):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            listing = self._desktop_tool(
                [WMCTRL, "-lx"],
                allow_failure=True,
                timeout=min(10.0, remaining),
            )
            if listing.returncode == 0:
                break
            if attempt + 1 < WINDOW_LIST_ATTEMPTS:
                time.sleep(min(WINDOW_LIST_RETRY_SECONDS, max(0.0, deadline - time.monotonic())))
        if listing is None or listing.returncode != 0:
            raise AutomationError("window_list_failed", "Desktop windows could not be listed.", 503)
        active_result = self._desktop_tool(
            [XDOTOOL, "getactivewindow"],
            allow_failure=True,
            timeout=max(0.1, deadline - time.monotonic()),
        )
        active_xid = None
        if active_result.returncode == 0:
            try:
                active_xid = "0x%08x" % int(active_result.stdout.strip())
            except ValueError:
                active_xid = None
        windows: list[dict[str, Any]] = []
        raw_lines = listing.stdout.decode("utf-8", "replace").splitlines()
        if len(raw_lines) > MAX_WINDOWS:
            raise AutomationError(
                "window_limit_exceeded", "The desktop has too many windows to enumerate safely.", 503
            )
        for raw_line in raw_lines:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AutomationError(
                    "window_list_timeout", "Desktop window enumeration timed out.", 504
                )
            fields = raw_line.split(None, 4)
            if len(fields) < 4 or not XID_RE.fullmatch(fields[0]):
                continue
            xid = "0x%08x" % int(fields[0], 16)
            # wmctrl -lx columns: XID, desktop, WM_CLASS, host, title.
            wm_class = fields[2][:256]
            title = fields[4][:4096] if len(fields) == 5 else ""
            properties = self._window_properties(xid, timeout=remaining)
            if properties is None:
                continue
            # xprop is the revalidation source for WM_CLASS when available.
            wm_class = properties["wm_class"] or wm_class
            windows.append(
                {
                    "id": xid,
                    "title": title,
                    "wm_class": wm_class,
                    "pid": properties["pid"],
                    "state": properties["state"],
                    "active": xid == active_xid,
                }
            )
        return windows

    def _window_properties(
        self, xid: str, *, timeout: float = 10
    ) -> dict[str, Any] | None:
        result = self._desktop_tool(
            [XPROP, "-id", xid, "WM_CLASS", "_NET_WM_PID", "_NET_WM_STATE"],
            allow_failure=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None
        text = result.stdout.decode("utf-8", "replace")
        class_match = re.search(r'^WM_CLASS\([^\n]*?=\s*"([^"]*)",\s*"([^"]*)"', text, re.MULTILINE)
        wm_class = (
            "%s.%s" % (class_match.group(1), class_match.group(2))
            if class_match
            else ""
        )
        pid_match = re.search(r"^_NET_WM_PID\([^\n]*?=\s*([0-9]+)\s*$", text, re.MULTILINE)
        pid = int(pid_match.group(1)) if pid_match else None
        states = set(re.findall(r"_NET_WM_STATE_[A-Z_]+", text))
        if "_NET_WM_STATE_HIDDEN" in states:
            state_name = "minimized"
        elif {
            "_NET_WM_STATE_MAXIMIZED_VERT",
            "_NET_WM_STATE_MAXIMIZED_HORZ",
        }.issubset(states):
            state_name = "maximized"
        else:
            state_name = "normal"
        return {"wm_class": wm_class[:256], "pid": pid, "state": state_name}

    def _revalidate_window(
        self,
        xid: str,
        *,
        expected_class: str,
        expected_pid: int | None,
        timeout: float = 10,
    ) -> None:
        properties = self._window_properties(_require_xid(xid), timeout=timeout)
        pid_changed = (
            expected_pid is not None
            and properties is not None
            and properties["pid"] != expected_pid
        )
        if (
            properties is None
            or properties["wm_class"] != expected_class
            or pid_changed
        ):
            raise AutomationError(
                "window_changed", "The window changed before the operation could run.", 409
            )

    def _desktop_tool(
        self,
        argv: Sequence[str],
        *,
        allow_failure: bool = False,
        timeout: float = 10,
    ) -> "BoundedResult":
        self._require_tool(argv[0])
        try:
            result = _run_bounded(
                argv,
                env=self.environment.build(),
                timeout=timeout,
                output_limit=MAX_TOOL_OUTPUT_BYTES,
            )
        except subprocess.TimeoutExpired:
            raise AutomationError("desktop_timeout", "The desktop operation timed out.", 504) from None
        if result.output_truncated:
            raise AutomationError("desktop_output_too_large", "Desktop tool output was too large.", 503)
        if not allow_failure and result.returncode != 0:
            raise AutomationError("desktop_operation_failed", "The desktop operation failed.", 503)
        return result

    @staticmethod
    def _require_tool(path: str) -> None:
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise AutomationError(
                "dependency_unavailable", "A required desktop automation tool is unavailable.", 503
            )


class BoundedResult:
    def __init__(self, returncode: int, stdout: bytes, stderr: bytes, output_truncated: bool):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.output_truncated = output_truncated


def _run_bounded(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    timeout: float,
    output_limit: int,
) -> BoundedResult:
    process = subprocess.Popen(
        list(argv),
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    captured: dict[str, tuple[bytes, bool]] = {}

    def drain(name: str, source: Any) -> None:
        value = bytearray()
        truncated = False
        try:
            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    break
                remaining = output_limit - len(value)
                if remaining > 0:
                    value.extend(chunk[:remaining])
                if len(chunk) > max(remaining, 0):
                    truncated = True
        finally:
            source.close()
            captured[name] = (bytes(value), truncated)

    output_threads = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in output_threads:
        thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise
    finally:
        for thread in output_threads:
            thread.join(timeout=2)
    stdout, stdout_truncated = captured.get("stdout", (b"", False))
    stderr, stderr_truncated = captured.get("stderr", (b"", False))
    return BoundedResult(
        process.returncode,
        stdout,
        stderr,
        stdout_truncated or stderr_truncated,
    )


def _validate_png(data: bytes) -> None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 45:
        raise AutomationError("invalid_screenshot", "The screenshot is not a valid PNG.", 503)
    offset = 8
    seen_ihdr = False
    seen_iend = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if length > len(data) or chunk_end > len(data):
            break
        chunk_data = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            break
        if not seen_ihdr:
            if chunk_type != b"IHDR" or length != 13:
                break
            width, height = struct.unpack(">II", chunk_data[:8])
            if not (1 <= width <= 16384 and 1 <= height <= 16384):
                break
            seen_ihdr = True
        if chunk_type == b"IEND":
            if length != 0 or chunk_end != len(data):
                break
            seen_iend = True
            offset = chunk_end
            break
        offset = chunk_end
    if not seen_ihdr or not seen_iend or offset != len(data):
        raise AutomationError("invalid_screenshot", "The screenshot is not a valid PNG.", 503)


def _require_xid(value: str) -> str:
    if not XID_RE.fullmatch(value):
        raise AutomationError("invalid_window_id", "The window id is invalid.", 400)
    return "0x%08x" % int(value, 16)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
