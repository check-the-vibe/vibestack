#!/usr/bin/env python3
"""Private catalog, installation, pairing and Linux-password API.

The public workspace service authenticates requests before this local backend.
No legacy HTML, script or style assets are served here.
"""

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from codecs import getincrementaldecoder
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setuplib as lib  # noqa: E402

COMMON_ROOT = os.environ.get(
    "VIBESTACK_COMMON_ROOT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"),
)
if COMMON_ROOT not in sys.path:
    sys.path.insert(0, COMMON_ROOT)
from vibestack_auth import ClientAuthError, WorkspaceClientStore  # noqa: E402
from vibestack_hosts import host_is_configured  # noqa: E402

PORT = int(os.environ.get("SETUP_PORT", "7999"))
INSTALLER = "/usr/local/bin/vibestack-install"
PASSWORD_HELPER = "/usr/local/bin/vibestack-password"

MAX_REQUEST_BODY_BYTES = 64 * 1024
MAX_COMPONENTS = 128
MAX_COMPONENT_ID_BYTES = 128
MAX_LOG_BYTES = 1024 * 1024
MAX_LOG_PAGE_BYTES = 64 * 1024
MAX_LOG_OFFSET = (1 << 63) - 1
MIN_PASSWORD_BYTES = 12
MAX_PASSWORD_BYTES = 256
MAX_PASSWORD_HELPER_RESPONSE_BYTES = 1024
PASSWORD_HELPER_TIMEOUT_SECONDS = 30

HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

_lock = threading.Lock()
_mirror_lock = threading.Lock()
_password_lock = threading.Lock()
_client_store = WorkspaceClientStore(os.environ.get("VIBESTACK_CLIENT_STATE_DIR", "/home/vibe/.vibestack"))
_job = {
    "running": False,
    "log": b"",
    "log_base": 0,
    "ok": None,
    "target": [],
    "phase": "idle",
}


class RequestError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _authority(value):
    if (
        not value
        or len(value) > 255
        or any(character.isspace() for character in value)
        or any(character in value for character in "/\\@,")
    ):
        raise ValueError("invalid authority")
    parsed = urlsplit("//" + value)
    if (
        not parsed.hostname
        or parsed.hostname.endswith(".")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid authority")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("invalid authority") from None
    if port == 0:
        raise ValueError("invalid authority")
    return parsed.hostname.lower(), port


def _host_allowed(host_name):
    if host_name in ("localhost", "127.0.0.1", "::1"):
        return True
    labels = host_name.split(".")
    return host_is_configured(host_name) or (
        len(labels) >= 4
        and labels[-2:] == ["ts", "net"]
        and all(HOST_LABEL_RE.fullmatch(label) for label in labels[:-2])
    )


def validate_request_source(handler):
    hosts = handler.headers.get_all("Host") or []
    if len(hosts) != 1:
        raise RequestError("invalid_host", "A single valid Host header is required.")
    try:
        host_name, host_port = _authority(hosts[0])
    except ValueError:
        raise RequestError(
            "invalid_host", "A single valid Host header is required."
        ) from None
    if not _host_allowed(host_name):
        raise RequestError(
            "host_not_allowed", "The request Host is not allowed.", 421
        )

    fetch_sites = handler.headers.get_all("Sec-Fetch-Site") or []
    if len(fetch_sites) > 1:
        raise RequestError(
            "invalid_request", "Duplicate Sec-Fetch-Site headers are not allowed."
        )
    if fetch_sites:
        fetch_site = fetch_sites[0].strip().lower()
        if fetch_site in ("cross-site", "same-site"):
            if handler.command not in ("GET", "HEAD"):
                raise RequestError(
                    "cross_origin", "Cross-origin requests are not allowed.", 403
                )
            modes = handler.headers.get_all("Sec-Fetch-Mode") or []
            destinations = handler.headers.get_all("Sec-Fetch-Dest") or []
            if len(modes) != 1 or len(destinations) != 1:
                raise RequestError("invalid_request", "Safe navigation fetch metadata is required.")
            if not (
                modes[0].strip().lower() == "navigate"
                and destinations[0].strip().lower() in ("document", "empty")
            ):
                raise RequestError(
                    "cross_origin", "Cross-origin requests are not allowed.", 403
                )
        if fetch_site not in ("same-origin", "none"):
            if fetch_site not in ("cross-site", "same-site"):
                raise RequestError("invalid_request", "Invalid Sec-Fetch-Site header.")

    origins = handler.headers.get_all("Origin") or []
    if not origins:
        return
    if len(origins) != 1 or origins[0] == "null":
        raise RequestError(
            "cross_origin", "Cross-origin requests are not allowed.", 403
        )
    parsed = urlsplit(origins[0])
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise RequestError(
            "cross_origin", "Cross-origin requests are not allowed.", 403
        )
    try:
        origin_port = parsed.port
    except ValueError:
        raise RequestError(
            "cross_origin", "Cross-origin requests are not allowed.", 403
        ) from None
    default_port = 443 if parsed.scheme == "https" else 80
    effective_origin_port = origin_port or default_port
    ports_match = (
        host_port is None and (origin_port is None or origin_port == default_port)
    ) or host_port == effective_origin_port
    if parsed.hostname.lower() != host_name or not ports_match:
        raise RequestError(
            "cross_origin", "Cross-origin requests are not allowed.", 403
        )


def _sanitize_log_text(text):
    """Keep service logs readable without echoing terminal control sequences."""
    text = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|$))", "", text)
    return "".join(
        character
        if character in "\n\t" or ord(character) >= 0x20
        else "\ufffd"
        for character in text
    )


def _append_log(text, *, newline=False):
    if not isinstance(text, str):
        text = str(text)
    text = _sanitize_log_text(text)
    if newline and not text.endswith("\n"):
        text += "\n"
    encoded = text.encode("utf-8", "replace")
    if not encoded:
        return

    with _lock:
        combined = _job["log"] + encoded
        if len(combined) > MAX_LOG_BYTES:
            drop = len(combined) - MAX_LOG_BYTES
            # Keep the retained prefix on a UTF-8 boundary. Offsets are byte
            # cursors and remain absolute even when old output is discarded.
            while drop < len(combined) and combined[drop] & 0xC0 == 0x80:
                drop += 1
            combined = combined[drop:]
            _job["log_base"] += drop
        _job["log"] = combined

    # Supervisor already rotates this stdout stream. Only fixed catalog IDs,
    # installer output, and server-generated status messages reach this path;
    # request bodies and headers are never mirrored.
    with _mirror_lock:
        sys.stdout.write(text)
        sys.stdout.flush()


def log_line(text):
    _append_log(text, newline=True)


def _job_status_locked(lease_held, *, lease_valid=True):
    """Build the public job state while `_lock` is held."""

    internal = bool(_job["running"])
    external = bool(lease_held and not internal) if lease_valid else None
    return {
        "running": internal or bool(lease_held),
        "external": external,
        "lease_valid": lease_valid,
        "ok": None if external else _job["ok"],
        "phase": "external" if external else _job["phase"],
        "target": [] if external else list(_job["target"]),
    }


def start_job(ids, phase="install"):
    """Kick off an install in the background. Returns False if one is running."""
    with _lock:
        if _job["running"]:
            return False
        # Publish the in-process job while still holding `_lock`. This prevents
        # a status request from briefly misclassifying our newly acquired lease
        # as an external CLI job.
        job_lock_fd = lib.acquire_install_job_lock(blocking=False)
        _job.update(
            running=True,
            log=b"",
            log_base=0,
            ok=None,
            target=list(ids),
            phase=phase,
        )
    try:
        threading.Thread(
            target=_run_job_entry,
            args=(list(ids), phase, job_lock_fd),
            daemon=True,
        ).start()
    except BaseException:
        with _lock:
            _job.update(running=False, ok=False)
        lib.release_install_job_lock(job_lock_fd)
        raise
    return True


def _run_job_entry(ids, phase, job_lock_fd):
    try:
        _run_job(ids, phase)
    finally:
        # Keep an unexpected worker failure from stranding the in-process flag
        # or the cross-process lease.
        with _lock:
            if _job["running"]:
                _job.update(running=False, ok=False)
        lib.release_install_job_lock(job_lock_fd)


def _run_job(ids, phase):
    ok = True
    try:
        if ids:
            log_line("[setup] installing: %s" % " ".join(ids))
            try:
                proc = subprocess.Popen(
                    ["sudo", "-n", INSTALLER] + ids,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                )
                decoder = getincrementaldecoder("utf-8")("replace")
                while True:
                    chunk = proc.stdout.read(8192)
                    if not chunk:
                        break
                    _append_log(decoder.decode(chunk))
                tail = decoder.decode(b"", final=True)
                if tail:
                    _append_log(tail)
                ok = proc.wait() == 0
            except Exception as exc:  # installer missing, sudo denied, ...
                log_line("[setup] error: %s" % exc)
                ok = False
        else:
            log_line("[setup] nothing to install")

        catalog = lib.catalog_for_runtime(lib.load_catalog())
        installed = lib.installed_ids(catalog)
        if phase == "install":
            _state, ok = lib.record_install_outcome(ids, installed, ok)
        else:
            # A zero installer exit is not enough: restore is successful only
            # after every requested component's probe has converged and every
            # saved ID still exists in this image's catalog.
            state = lib.load_state()
            unknown = lib.unknown_for_state(catalog, state)
            unsupported = lib.unsupported_for_state(catalog, state)
            if unknown:
                log_line(
                    "[setup] saved component IDs unavailable in this image: %s"
                    % " ".join(unknown)
                )
            if unsupported:
                log_line(
                    "[setup] saved component IDs unavailable in this runtime (%s): %s"
                    % (catalog["architecture"], " ".join(unsupported))
                )
            ok = (
                ok
                and not unknown
                and not unsupported
                and all(component in installed for component in ids)
            )
    except lib.StateError as exc:
        log_line("[setup] saved state error: %s" % exc.code)
        ok = False
    except Exception as exc:  # catalog/probe/state I/O must not strand running=true
        log_line("[setup] operation error: %s" % type(exc).__name__)
        ok = False
    finally:
        if not ok:
            log_line("[setup] requested components are still missing")
        log_line("[setup] %s" % ("done" if ok else "finished with errors"))
        with _lock:
            _job.update(running=False, ok=ok)


def auto_restore():
    """Components live in the container filesystem, so a recreated container
    loses them. Reinstall whatever the saved selection says should be here."""
    try:
        state = lib.load_state()
    except lib.StateError as exc:
        print("[setup] saved state error: %s" % exc.code, flush=True)
        return
    if not state.get("completed") or not state.get("auto_restore", True):
        return
    catalog = lib.catalog_for_runtime(lib.load_catalog())
    unknown = lib.unknown_for_state(catalog, state)
    unsupported = lib.unsupported_for_state(catalog, state)
    missing = lib.restorable_missing_for_state(catalog, state)
    if missing:
        try:
            start_job(missing, phase="restore")
        except lib.StateError as exc:
            # A CLI install can legitimately span a setup-service restart. It
            # owns the process-shared lease, so defer restore and keep serving;
            # every unsafe/unreadable lock condition still aborts startup.
            if exc.code != "job_running":
                raise
            log_line("[setup] restore deferred: another installer holds the setup lease")
    if unknown:
        log_line(
            "[setup] saved component IDs unavailable in this image: %s"
            % " ".join(unknown)
        )
    if unsupported:
        log_line(
            "[setup] saved component IDs unavailable in this runtime (%s): %s"
            % (catalog["architecture"], " ".join(unsupported))
        )


class PasswordBackendError(RuntimeError):
    """A generic, deliberately non-secret-bearing helper failure."""


def _run_password_helper(command, password=None):
    if command not in ("status", "set"):
        raise PasswordBackendError("Password helper request failed.")
    input_data = None
    if command == "set":
        # The fixed argv is important: plaintext is sent only through stdin.
        input_data = json.dumps(
            {"password": password}, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    try:
        result = subprocess.run(
            ["sudo", "-n", PASSWORD_HELPER, command],
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=PASSWORD_HELPER_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise PasswordBackendError("Password helper request failed.") from None
    if (
        result.returncode != 0
        or len(result.stdout) > MAX_PASSWORD_HELPER_RESPONSE_BYTES
    ):
        raise PasswordBackendError("Password helper request failed.")
    try:
        payload = json.loads(result.stdout.decode("utf-8", "strict"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise PasswordBackendError("Password helper request failed.") from None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"password_configured"}
        or not isinstance(payload["password_configured"], bool)
        or (command == "set" and not payload["password_configured"])
    ):
        raise PasswordBackendError("Password helper request failed.")
    return {
        "password_configured": payload["password_configured"],
        "sudo_password_required": True,
    }


def password_status():
    return _run_password_helper("status")


def set_linux_password(password):
    return _run_password_helper("set", password=password)


def validate_password_request(body):
    unknown = set(body) - {"password", "confirmation"}
    missing = {"password", "confirmation"} - set(body)
    if unknown or missing:
        raise RequestError(
            "invalid_request", "The JSON object has invalid or missing fields."
        )
    password = body["password"]
    confirmation = body["confirmation"]
    if not isinstance(password, str) or not isinstance(confirmation, str):
        raise RequestError(
            "invalid_password", "Password and confirmation must be strings."
        )
    try:
        password_bytes = password.encode("utf-8", "strict")
        confirmation_bytes = confirmation.encode("utf-8", "strict")
    except UnicodeEncodeError:
        raise RequestError(
            "invalid_password", "Password must be valid UTF-8."
        ) from None
    if not secrets.compare_digest(password_bytes, confirmation_bytes):
        raise RequestError("password_mismatch", "Passwords do not match.")
    if not MIN_PASSWORD_BYTES <= len(password_bytes) <= MAX_PASSWORD_BYTES:
        raise RequestError(
            "invalid_password",
            "Password must contain 12 to 256 UTF-8 bytes.",
        )
    if password.isspace() or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in password
    ):
        raise RequestError(
            "invalid_password", "Password contains unsupported control characters."
        )
    return password


class Handler(BaseHTTPRequestHandler):
    server_version = "VibeStackSetup"

    def log_message(self, fmt, *args):  # keep supervisor logs readable
        pass

    # -- helpers ---------------------------------------------------------
    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _json(self, code, payload):
        self._send(
            code,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            ),
            "application/json; charset=utf-8",
        )

    def _body(self):
        transfer_encoding = self.headers.get_all("Transfer-Encoding") or []
        if transfer_encoding:
            raise RequestError(
                "invalid_request", "Transfer-Encoding is not supported."
            )

        content_types = self.headers.get_all("Content-Type") or []
        if len(content_types) != 1:
            if len(content_types) > 1:
                raise RequestError(
                    "invalid_request", "Duplicate Content-Type headers are not allowed."
                )
            raise RequestError(
                "unsupported_media_type",
                "Content-Type must be application/json.",
                415,
            )
        content_type_parts = [part.strip() for part in content_types[0].split(";")]
        if not content_type_parts or content_type_parts[0].lower() != "application/json":
            raise RequestError(
                "unsupported_media_type",
                "Content-Type must be application/json.",
                415,
            )
        for parameter in content_type_parts[1:]:
            name, separator, value = parameter.partition("=")
            if (
                not separator
                or name.strip().lower() != "charset"
                or value.strip().strip('"').lower() not in ("utf-8", "utf8")
            ):
                raise RequestError(
                    "unsupported_media_type",
                    "Only UTF-8 application/json is supported.",
                    415,
                )

        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) != 1:
            if len(lengths) > 1:
                raise RequestError(
                    "invalid_request", "Duplicate Content-Length headers are not allowed."
                )
            raise RequestError(
                "length_required", "A Content-Length header is required.", 411
            )
        try:
            raw_length = lengths[0]
            if not raw_length or not raw_length.isascii() or not raw_length.isdecimal():
                raise ValueError
            length = int(raw_length, 10)
        except (TypeError, ValueError):
            raise RequestError(
                "invalid_request", "Content-Length must be a non-negative integer."
            ) from None
        if length > MAX_REQUEST_BODY_BYTES:
            raise RequestError(
                "request_too_large",
                "The request body exceeds %d bytes." % MAX_REQUEST_BODY_BYTES,
                413,
            )
        if length == 0:
            raise RequestError("invalid_json", "A JSON object body is required.")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise RequestError("invalid_request", "The request body was incomplete.")
        try:
            body = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    ValueError("non-finite JSON number")
                ),
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            raise RequestError("invalid_json", "The body must be one JSON object.") from None
        if not isinstance(body, dict):
            raise RequestError("invalid_json", "The body must be one JSON object.")
        return body

    def _validate_body_keys(self, body, allowed, required=()):
        unknown = set(body) - set(allowed)
        missing = set(required) - set(body)
        if unknown or missing:
            raise RequestError(
                "invalid_request", "The JSON object has invalid or missing fields."
            )

    def _error(self, error):
        self.close_connection = True
        self._json(error.status, {"code": error.code, "error": error.message})

    def _state_payload(self):
        catalog = lib.catalog_for_runtime(lib.load_catalog())
        installed = lib.installed_ids(catalog)
        try:
            state = lib.load_state()
        except lib.StateError as exc:
            state = None
            state_valid = False
            state_error = {"code": exc.code, "message": exc.message}
            missing = []
            unknown = []
            unsupported = []
        else:
            state_valid = True
            state_error = None
            missing = lib.missing_for_state(catalog, state)
            unknown = lib.unknown_for_state(catalog, state)
            unsupported = lib.unsupported_for_state(catalog, state)
        try:
            lease_held = lib.install_job_lock_held()
            lease_valid = True
        except lib.StateError as exc:
            # A substituted or otherwise unsafe lease file makes setup state
            # operationally indeterminate. Preserve the explicit state envelope
            # and fail closed rather than claiming that no install is running.
            lease_held = False
            lease_valid = False
            state = None
            state_valid = False
            state_error = {"code": exc.code, "message": exc.message}
            missing = []
            unknown = []
            unsupported = []
        with _lock:
            log_bytes = _job["log"]
            job = {
                **_job_status_locked(lease_held, lease_valid=lease_valid),
                "length": _job["log_base"] + len(log_bytes),
                "available_from": _job["log_base"],
            }
        return {
            "catalog": catalog,
            "architecture": catalog["architecture"],
            "installed": installed,
            "state": state,
            "state_valid": state_valid,
            "state_error": state_error,
            "job": job,
            "missing": missing,
            "unknown_selected": unknown,
            "unsupported_selected": unsupported,
            "authentication": password_status(),
        }

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        try:
            validate_request_source(self)
        except RequestError as exc:
            self._error(exc)
            return
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(
            parsed.query, keep_blank_values=True, max_num_fields=8
        )

        if path == "/api/state":
            try:
                payload = self._state_payload()
            except PasswordBackendError:
                self._json(
                    503,
                    {
                        "code": "password_status_unavailable",
                        "error": "Linux password status is temporarily unavailable.",
                    },
                )
                return
            self._json(200, payload)
        elif path == "/api/discovery":
            if query:
                self._json(400, {"code": "invalid_query", "error": "discovery does not accept query parameters"})
                return
            try:
                identity = _client_store.identity()
            except ClientAuthError as exc:
                self._json(exc.status, {"code": exc.code, "error": exc.message})
                return
            self._json(
                200,
                {
                    "kind": "workspace",
                    "identity": identity,
                    "version": "0.2.0",
                    "api_versions": ["1"],
                    "api_roots": {"automation": "/api/v1/automation", "control": "/api/v1", "setup": "/setup/api"},
                    "documentation": {"agents": "/AGENTS.md", "cli": "/CLI.md", "automation": "/AUTOMATION.md", "runner": "/RUNNER.md"},
                    "pairing": {"request": "/api/v1/automation/pairing/requests", "approval": "/SERVICE.md", "permissions": ["workspace"]},
                    "cli": {"installer": "/cli.sh", "compatible": ">=0.2.0 <1.0.0"},
                },
            )
        elif path == "/api/clients":
            if query:
                self._json(400, {"code": "invalid_query", "error": "client listing does not accept query parameters"})
                return
            try:
                self._json(200, _client_store.admin_state())
            except ClientAuthError as exc:
                self._json(exc.status, {"code": exc.code, "error": exc.message})
        elif path == "/api/log":
            try:
                lease_held = lib.install_job_lock_held()
            except lib.StateError as exc:
                self._json(409, {"code": exc.code, "error": exc.message})
                return
            try:
                if set(query) - {"offset"} or len(query.get("offset", ["0"])) != 1:
                    raise ValueError
                raw_offset = query.get("offset", ["0"])[0]
                if (
                    not raw_offset
                    or not raw_offset.isascii()
                    or not raw_offset.isdecimal()
                    or len(raw_offset) > 19
                ):
                    raise ValueError
                offset = int(raw_offset, 10)
                if offset > MAX_LOG_OFFSET:
                    raise ValueError
            except (TypeError, ValueError):
                self._json(
                    400,
                    {"code": "invalid_offset", "error": "offset must be a valid log cursor"},
                )
                return
            with _lock:
                data = _job["log"]
                base = _job["log_base"]
                end = base + len(data)
                if offset > end:
                    self._json(
                        400,
                        {
                            "code": "invalid_offset",
                            "error": "offset is beyond the current log",
                        },
                    )
                    return
                truncated = offset < base
                start = max(offset, base) - base
                page_end = min(len(data), start + MAX_LOG_PAGE_BYTES)
                if page_end < len(data):
                    while page_end > start and data[page_end] & 0xC0 == 0x80:
                        page_end -= 1
                page = data[start:page_end]
                text = page.decode("utf-8", "strict")
                payload = {
                    "text": text,
                    "offset": base + page_end,
                    "truncated": truncated,
                    "more": page_end < len(data),
                    **_job_status_locked(lease_held),
                }
            self._json(200, payload)
        else:
            self._send(404, b"not found")

    def do_POST(self):
        try:
            validate_request_source(self)
            parsed = urlsplit(self.path)
            if parsed.query or parsed.fragment:
                raise RequestError(
                    "invalid_request", "Mutation routes do not accept a query string."
                )
            path = parsed.path
            pairing_action = re.fullmatch(r"/api/pairings/([A-Z2-9]{4}-[A-Z2-9]{4})/(approve|deny)", path)
            client_revoke = re.fullmatch(r"/api/clients/([0-9a-f]{32})/revoke", path)
            if path not in (
                "/api/install",
                "/api/skip",
                "/api/complete",
                "/api/reset",
                "/api/password",
            ) and pairing_action is None and client_revoke is None:
                self._send(404, b"not found")
                return
            body = self._body()

            if pairing_action is not None:
                self._validate_body_keys(body, set())
                try:
                    payload = (
                        _client_store.approve(pairing_action.group(1))
                        if pairing_action.group(2) == "approve"
                        else _client_store.deny(pairing_action.group(1))
                    )
                except ClientAuthError as exc:
                    raise RequestError(exc.code, exc.message, exc.status) from None
                self._json(200, {"pairing": payload})
            elif client_revoke is not None:
                self._validate_body_keys(body, set())
                try:
                    payload = _client_store.revoke(client_revoke.group(1))
                except ClientAuthError as exc:
                    raise RequestError(exc.code, exc.message, exc.status) from None
                self._json(200, {"client": payload})
            elif path == "/api/password":
                password = validate_password_request(body)
                if not _password_lock.acquire(blocking=False):
                    raise RequestError(
                        "password_update_running",
                        "A password update is already running.",
                        409,
                    )
                try:
                    # Current-password authentication is intentionally omitted:
                    # this setup service is an admin surface inside the trusted
                    # loopback/Tailscale boundary, including for later changes.
                    authentication = set_linux_password(password)
                except PasswordBackendError:
                    raise RequestError(
                        "password_update_failed",
                        "The Linux password could not be updated.",
                        500,
                    ) from None
                finally:
                    _password_lock.release()
                self._json(200, {"authentication": authentication})
            elif path == "/api/install":
                self._validate_body_keys(body, {"components"}, {"components"})
                components = body["components"]
                if (
                    not isinstance(components, list)
                    or len(components) > MAX_COMPONENTS
                    or any(
                        not isinstance(component, str)
                        or not component
                        or len(component.encode("utf-8")) > MAX_COMPONENT_ID_BYTES
                        for component in components
                    )
                ):
                    raise RequestError(
                        "invalid_components", "components must be a bounded list of IDs."
                    )
                catalog = lib.catalog_for_runtime(lib.load_catalog())
                known = {component["id"] for component in catalog["components"]}
                if any(component not in known for component in components):
                    raise RequestError(
                        "invalid_components", "components contains an unknown catalog ID."
                    )
                wanted = lib.resolve(catalog, components)
                index = lib.by_id(catalog)
                unsupported = [
                    component
                    for component in wanted
                    if not lib.component_supported(index[component])
                ]
                if unsupported:
                    raise RequestError(
                        "unsupported_architecture",
                        "components are unavailable in this runtime: %s"
                        % " ".join(unsupported),
                        409,
                    )
                if not start_job(wanted):
                    self._json(
                        409,
                        {
                            "code": "job_running",
                            "error": "an install is already running",
                        },
                    )
                    return
                self._json(202, {"started": wanted})
            else:
                self._validate_body_keys(body, set())
                # Keep state mutations ordered with the in-process installer.
                # _run_job leaves `running` true until its state transaction is
                # durable, so reset/skip/complete cannot erase or supersede an
                # install result while it is being recorded.
                job_lock_fd = lib.acquire_install_job_lock(blocking=False)
                try:
                    with _lock:
                        if _job["running"]:
                            raise RequestError(
                                "job_running", "an install is already running", 409
                            )
                        if path == "/api/skip":
                            state = lib.mark_complete([], skipped=True)
                        elif path == "/api/complete":
                            catalog = lib.catalog_for_runtime(lib.load_catalog())
                            state = lib.mark_complete(lib.installed_ids(catalog))
                        else:
                            lib.clear_state()
                            state = lib.default_state()
                finally:
                    lib.release_install_job_lock(job_lock_fd)
                self._json(200, {"state": state})
        except RequestError as exc:
            self._error(exc)
        except lib.StateError as exc:
            self.close_connection = True
            self._json(409, {"code": exc.code, "error": exc.message})


def main():
    # VIBESTACK_SKIP_SETUP is applied once by entrypoint through the
    # lease-aware vibestack-setup CLI. Do not duplicate that mutation here: a
    # CLI installer may legitimately still own the cross-process lease when
    # Supervisor starts or restarts this service.
    auto_restore()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    print("[setup] listening on 127.0.0.1:%d" % PORT, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
