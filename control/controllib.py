#!/usr/bin/env python3
"""Core implementation for the VibeStack desktop control service.

The web service runs as ``vibe``.  Supervisor access and supervisor-owned log
files are reached through ``vibestack-control``, a deliberately small helper
whose arguments are all validated against the constants in this module.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


API_VERSION = "1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7998
DEFAULT_DISPLAY = ":0"
DEFAULT_DISK_PATH = "/home/vibe"
CONTROL_HELPER = "/usr/local/bin/vibestack-control"
SUPERVISORCTL = "/usr/bin/supervisorctl"
SUPERVISOR_CONFIG = "/etc/supervisor/supervisord.conf"
XRANDR = "/usr/bin/xrandr"
CVT = "/usr/bin/cvt"

# supervisorctl runs through the root-only helper. Never inherit cwd, Python
# paths, HOME, or configuration-affecting environment from the desktop user.
SUPERVISOR_ENV: Mapping[str, str] = {
    "HOME": "/root",
    "USER": "root",
    "LOGNAME": "root",
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    # The fixed Supervisor config references these values while parsing its
    # program sections. They do not influence the already-running daemon.
    "RESOLUTION": "1920x1200",
    "VNC_PORT": "5900",
    "NOVNC_PORT": "6080",
    "TTYD_PORT": "7681",
    "SETUP_PORT": "7999",
    "CONTROL_PORT": "7998",
    "AUTOMATION_PORT": "7997",
}

SUPPORTED_RESOLUTIONS = (
    "1280x800",
    "1368x768",
    "1440x900",
    "1600x900",
    "1600x1200",
    "1920x1200",
)
MIN_DISPLAY_WIDTH = 640
MIN_DISPLAY_HEIGHT = 480
MAX_DISPLAY_WIDTH = 1920
MAX_DISPLAY_HEIGHT = 1200
DISPLAY_WIDTH_STEP = 8
DISPLAY_HEIGHT_STEP = 2

# Browser-facing names never become supervisor program names or filesystem
# paths.  Only this mapping crosses that boundary.
SERVICE_PROGRAMS: Mapping[str, str] = {
    "desktop": "xfce4",
    "vnc": "x11vnc",
    "terminal": "ttyd",
    "setup": "vibestack-setup",
}
SERVICE_LOGS: Mapping[str, str] = {
    "desktop": "/data/logs/vibestack/services/xfce4.log",
    "vnc": "/data/logs/vibestack/services/x11vnc.log",
    "terminal": "/data/logs/vibestack/services/ttyd.log",
    "setup": "/data/logs/vibestack/services/vibestack-setup.log",
}
OPTIONAL_SERVICE_PROGRAMS: Mapping[str, str] = {
    "ssh": "ssh",
    "native-vnc": "native-vnc",
    "editor": "code-server",
}
OPTIONAL_SERVICE_LOGS: Mapping[str, str] = {
    "ssh": "/data/logs/vibestack/services/ssh.log",
    "native-vnc": "/data/logs/vibestack/services/native-vnc.log",
    "editor": "/data/logs/vibestack/services/code-server.log",
}
MANAGED_SERVICE_PROGRAMS: Mapping[str, str] = {
    **SERVICE_PROGRAMS,
    **OPTIONAL_SERVICE_PROGRAMS,
}
MANAGED_SERVICE_LOGS: Mapping[str, str] = {
    **SERVICE_LOGS,
    **OPTIONAL_SERVICE_LOGS,
}

DEFAULT_LOG_LIMIT = 100
MAX_LOG_LIMIT = 200
MAX_LOG_LINE_BYTES = 4096
MAX_LOG_PAGE_BYTES = 64 * 1024
# Leave room for pagination metadata plus the logical service field which the
# privileged helper adds after the file reader returns.
LOG_ENVELOPE_RESERVE_BYTES = 128
MAX_HELPER_OUTPUT_BYTES = 128 * 1024
COMMAND_TIMEOUT_SECONDS = 10
# Supervisor waits for each program's ``startsecs`` before reporting a
# successful restart. The desktop intentionally has an 18-second grace period,
# so restart calls need a larger (but still bounded) budget at both helper
# process boundaries.
SUPERVISOR_RESTART_TIMEOUT_SECONDS = 30
HELPER_RESTART_TIMEOUT_SECONDS = 45
OUTPUT_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
RESOLUTION_RE = re.compile(r"^([0-9]{1,4})x([0-9]{1,4})$")
MODELINE_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
MODELINE_FLAG_RE = re.compile(r"^[+-](?:h|v)sync$", re.IGNORECASE)
ANSI_ESCAPE_RE = re.compile(
    rb"(?:\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\))"
)


class ControlError(Exception):
    """A safe, structured error suitable for returning through the API."""

    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class DisplayState:
    output: str
    resolution: str
    advertised_resolutions: tuple[str, ...]
    maximum_width: int
    maximum_height: int

    def payload(self) -> dict[str, Any]:
        available = [
            resolution
            for resolution in SUPPORTED_RESOLUTIONS
            if resolution in self.advertised_resolutions
        ]
        if self.resolution not in available:
            available.insert(0, self.resolution)
        return {
            "resolution": self.resolution,
            "availableResolutions": available,
            "supportedResolutions": list(SUPPORTED_RESOLUTIONS),
            "dynamicResize": True,
            "bounds": {
                "minWidth": min(MIN_DISPLAY_WIDTH, self.maximum_width),
                "minHeight": min(MIN_DISPLAY_HEIGHT, self.maximum_height),
                "maxWidth": min(MAX_DISPLAY_WIDTH, self.maximum_width),
                "maxHeight": min(MAX_DISPLAY_HEIGHT, self.maximum_height),
                "widthStep": DISPLAY_WIDTH_STEP,
                "heightStep": DISPLAY_HEIGHT_STEP,
            },
        }


def require_service(service: str) -> str:
    """Return a known logical service or raise a safe client error."""

    if service not in MANAGED_SERVICE_PROGRAMS:
        raise ControlError("unknown_service", "Unknown logical service.", 404)
    return service


def require_resolution(resolution: object) -> str:
    """Return a bounded, aligned resolution or raise a safe client error."""

    match = RESOLUTION_RE.fullmatch(resolution) if isinstance(resolution, str) else None
    if match:
        width, height = (int(value) for value in match.groups())
        valid = (
            MIN_DISPLAY_WIDTH <= width <= MAX_DISPLAY_WIDTH
            and MIN_DISPLAY_HEIGHT <= height <= MAX_DISPLAY_HEIGHT
            and width % DISPLAY_WIDTH_STEP == 0
            and height % DISPLAY_HEIGHT_STEP == 0
        )
    else:
        valid = False
    if not valid:
        raise ControlError(
            "unsupported_resolution",
            (
                "Resolution must be between %dx%d and %dx%d, with width aligned "
                "to %d pixels and height aligned to %d pixels."
            )
            % (
                MIN_DISPLAY_WIDTH,
                MIN_DISPLAY_HEIGHT,
                MAX_DISPLAY_WIDTH,
                MAX_DISPLAY_HEIGHT,
                DISPLAY_WIDTH_STEP,
                DISPLAY_HEIGHT_STEP,
            ),
            400,
        )
    return f"{width}x{height}"


def parse_modeline(output: str) -> list[str]:
    """Extract only numeric timings and sync flags from cvt output."""

    for line in output.splitlines():
        if not line.lstrip().startswith("Modeline "):
            continue
        try:
            fields = shlex.split(line)
        except ValueError:
            break
        timings = fields[2:] if len(fields) >= 3 and fields[0] == "Modeline" else []
        if (
            len(timings) >= 9
            and all(MODELINE_NUMBER_RE.fullmatch(value) for value in timings[:9])
            and all(MODELINE_FLAG_RE.fullmatch(value) for value in timings[9:])
        ):
            return timings
        break
    raise ControlError("display_mode_generation_failed", "Display mode generation failed.", 502)


def _command_environment(display: str = DEFAULT_DISPLAY) -> dict[str, str]:
    env = os.environ.copy()
    env.update(DISPLAY=display, LC_ALL="C", LANG="C")
    return env


def run_command(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run an argv-only command.  No caller in this module uses a shell."""

    return subprocess.run(list(argv), **kwargs)


def parse_xrandr(output: str) -> DisplayState:
    """Parse the connected output, active mode, and advertised mode names."""

    screen_current: str | None = None
    match = re.search(r"\bcurrent\s+(\d+)\s+x\s+(\d+)\b", output)
    if match:
        screen_current = "%sx%s" % match.groups()
    maximum = re.search(r"\bmaximum\s+(\d+)\s+x\s+(\d+)\b", output)
    if not maximum:
        raise ControlError(
            "display_probe_failed", "The maximum display resolution could not be read."
        )
    maximum_width, maximum_height = (int(value) for value in maximum.groups())

    connected_output: str | None = None
    geometry_current: str | None = None
    advertised: list[str] = []
    marked_current: str | None = None
    in_connected_output = False

    for line in output.splitlines():
        connected = re.match(r"^(\S+)\s+connected(?:\s+(\d+x\d+)\+\d+\+\d+)?", line)
        if connected and connected_output is None:
            candidate = connected.group(1)
            if not OUTPUT_NAME_RE.fullmatch(candidate):
                raise ControlError(
                    "display_probe_failed", "The display output name is invalid."
                )
            connected_output = candidate
            geometry_current = connected.group(2)
            in_connected_output = True
            continue
        if re.match(r"^\S+\s+(?:connected|disconnected)\b", line):
            in_connected_output = False
            continue
        if not in_connected_output:
            continue

        mode = re.match(r"^\s+(\d+x\d+)\s+(.+)$", line)
        if not mode:
            continue
        name, details = mode.groups()
        if name not in advertised:
            advertised.append(name)
        if "*" in details:
            marked_current = name

    if connected_output is None:
        raise ControlError("display_unavailable", "No connected display was found.")

    resolution = marked_current or geometry_current or screen_current
    if resolution is None or not RESOLUTION_RE.fullmatch(resolution):
        raise ControlError(
            "display_probe_failed", "The current display resolution could not be read."
        )
    if resolution not in advertised:
        advertised.append(resolution)
    return DisplayState(
        connected_output,
        resolution,
        tuple(advertised),
        maximum_width,
        maximum_height,
    )


def _safe_detail(text: str, limit: int = 512) -> str:
    """Make command output safe and small enough for a JSON response."""

    value = " ".join(text.replace("\x00", "").split())
    return value[:limit]


def _json_from_process(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    output = proc.stdout or ""
    if len(output.encode("utf-8", "replace")) > MAX_HELPER_OUTPUT_BYTES:
        raise ControlError("control_helper_failed", "Control helper output was too large.")
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        payload = None
    if proc.returncode != 0:
        if isinstance(payload, dict):
            code = payload.get("code")
            message = payload.get("message")
            if isinstance(code, str) and isinstance(message, str):
                raise ControlError(code, message, 503)
        raise ControlError("control_helper_failed", "The control helper failed.")
    if not isinstance(payload, dict):
        raise ControlError("control_helper_failed", "Control helper returned invalid data.")
    return payload


class ControlBackend:
    """OS-facing operations used by the HTTP handler.

    ``runner`` is injectable so the command boundary can be exhaustively tested
    without a live X server, sudo, or supervisord.
    """

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
        helper_path: str = CONTROL_HELPER,
        display: str = DEFAULT_DISPLAY,
        disk_path: str = DEFAULT_DISK_PATH,
    ) -> None:
        self.runner = runner
        self.helper_path = helper_path
        self.display = display
        self.disk_path = disk_path
        self._generated_display_modes: set[str] = set()

    def _run_helper(self, arguments: Sequence[str]) -> dict[str, Any]:
        argv = ["/usr/bin/sudo", "-n", self.helper_path, *arguments]
        timeout = (
            HELPER_RESTART_TIMEOUT_SECONDS
            if arguments and arguments[0] in ("start", "restart")
            else COMMAND_TIMEOUT_SECONDS
        )
        try:
            proc = self.runner(
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                env=_command_environment(self.display),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ControlError("control_helper_unavailable", "Control helper is unavailable.")
        return _json_from_process(proc)

    def service_status(self, service: str) -> dict[str, Any]:
        require_service(service)
        payload = self._run_helper(("status", service))
        if payload.get("service") != service or not isinstance(payload.get("state"), str):
            raise ControlError("control_helper_failed", "Control helper returned invalid status.")
        return payload

    def restart_service(self, service: str) -> dict[str, Any]:
        require_service(service)
        payload = self._run_helper(("restart", service))
        if payload.get("service") != service or payload.get("restarted") is not True:
            raise ControlError("service_restart_failed", "The service could not be restarted.", 502)
        return payload

    def set_service_state(self, service: str, running: bool) -> dict[str, Any]:
        require_service(service)
        action = "start" if running else "stop"
        payload = self._run_helper((action, service))
        expected = "RUNNING" if running else "STOPPED"
        if payload.get("service") != service or payload.get("state") != expected:
            raise ControlError("service_update_failed", "The service did not reach the requested state.", 502)
        payload["operation"] = action
        return payload

    def service_logs(
        self, service: str, cursor: int | None, limit: int
    ) -> dict[str, Any]:
        require_service(service)
        if cursor is not None and (not isinstance(cursor, int) or cursor < 0):
            raise ControlError("invalid_cursor", "Cursor must be a non-negative integer.", 400)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LOG_LIMIT:
            raise ControlError(
                "invalid_limit", "Limit must be between 1 and %d." % MAX_LOG_LIMIT, 400
            )
        arguments = ["logs", service, "--limit", str(limit)]
        if cursor is not None:
            arguments.extend(("--cursor", str(cursor)))
        payload = self._run_helper(arguments)
        if payload.get("service") != service or not isinstance(payload.get("lines"), list):
            raise ControlError("control_helper_failed", "Control helper returned invalid logs.")
        return payload

    def _xrandr(self) -> DisplayState:
        try:
            proc = self.runner(
                [XRANDR, "--query"],
                capture_output=True,
                text=True,
                check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
                env=_command_environment(self.display),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ControlError("display_unavailable", "Display service is unavailable.")
        if proc.returncode != 0:
            raise ControlError("display_unavailable", "Display service is unavailable.")
        return parse_xrandr(proc.stdout or "")

    def get_display(self) -> dict[str, Any]:
        return self._xrandr().payload()

    def _create_display_mode(self, output: str, resolution: str) -> bool:
        width, height = resolution.split("x", 1)
        try:
            generated = self.runner(
                [CVT, width, height, "60"],
                capture_output=True,
                text=True,
                check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
                env=_command_environment(self.display),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ControlError(
                "display_mode_generation_failed", "Display mode generation failed.", 502
            )
        if generated.returncode != 0:
            raise ControlError(
                "display_mode_generation_failed", "Display mode generation failed.", 502
            )
        timings = parse_modeline(generated.stdout or "")

        try:
            created = self.runner(
                [XRANDR, "--newmode", resolution, *timings],
                capture_output=True,
                text=True,
                check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
                env=_command_environment(self.display),
            )
            attached = self.runner(
                [XRANDR, "--addmode", output, resolution],
                capture_output=True,
                text=True,
                check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
                env=_command_environment(self.display),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ControlError("display_mode_unavailable", "Display mode is unavailable.", 502)
        # --newmode may report that an identical mode already exists. A
        # successful --addmode is sufficient in that case.
        if attached.returncode != 0:
            raise ControlError("display_mode_unavailable", "Display mode is unavailable.", 502)
        return created.returncode == 0

    def set_display(self, resolution: object) -> dict[str, Any]:
        wanted = require_resolution(resolution)
        before = self._xrandr()
        wanted_width, wanted_height = (int(value) for value in wanted.split("x", 1))
        if wanted_width > before.maximum_width or wanted_height > before.maximum_height:
            raise ControlError(
                "display_mode_unavailable",
                "Resolution exceeds this desktop's framebuffer bounds.",
                409,
            )
        if wanted not in before.advertised_resolutions:
            if self._create_display_mode(before.output, wanted):
                self._generated_display_modes.add(wanted)
        try:
            proc = self.runner(
                [XRANDR, "--output", before.output, "--mode", wanted],
                capture_output=True,
                text=True,
                check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
                env=_command_environment(self.display),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ControlError("display_change_failed", "Display resolution change failed.", 502)
        if proc.returncode != 0:
            raise ControlError("display_change_failed", "Display resolution change failed.", 502)
        after = self._xrandr()
        if after.resolution != wanted:
            raise ControlError(
                "display_change_unconfirmed",
                "Display resolution change could not be confirmed.",
                502,
            )
        if before.resolution in self._generated_display_modes and before.resolution != wanted:
            # Auto-match can create several viewport-shaped modes over time.
            # Once the prior mode is inactive, remove it so a long-running
            # desktop does not accumulate one mode for every browser height.
            for arguments in (
                ("--delmode", before.output, before.resolution),
                ("--rmmode", before.resolution),
            ):
                try:
                    self.runner(
                        [XRANDR, *arguments],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=COMMAND_TIMEOUT_SECONDS,
                        env=_command_environment(self.display),
                    )
                except (OSError, subprocess.TimeoutExpired):
                    break
            self._generated_display_modes.discard(before.resolution)
        return after.payload()

    def status_payload(self) -> dict[str, Any]:
        services: dict[str, Any] = {}
        for service in MANAGED_SERVICE_PROGRAMS:
            try:
                services[service] = self.service_status(service)
            except ControlError as exc:
                services[service] = {
                    "service": service,
                    "state": "UNKNOWN",
                    "error": {"code": exc.code, "message": exc.message},
                }

        try:
            display = self.get_display()
        except ControlError as exc:
            display = {
                "resolution": None,
                "availableResolutions": [],
                "supportedResolutions": list(SUPPORTED_RESOLUTIONS),
                "error": {"code": exc.code, "message": exc.message},
            }

        try:
            with open("/proc/uptime", "r", encoding="ascii") as handle:
                uptime = int(float(handle.read().split()[0]))
        except (OSError, ValueError, IndexError):
            uptime = None

        try:
            disk = shutil.disk_usage(self.disk_path)
            disk_payload: dict[str, Any] = {
                "path": self.disk_path,
                "totalBytes": disk.total,
                "usedBytes": disk.used,
                "availableBytes": disk.free,
            }
        except OSError:
            disk_payload = {
                "path": self.disk_path,
                "totalBytes": None,
                "usedBytes": None,
                "availableBytes": None,
            }

        return {
            "apiVersion": API_VERSION,
            "uptimeSeconds": uptime,
            "disk": disk_payload,
            "display": display,
            "services": services,
        }


def _sanitize_log_line(raw: bytes) -> str:
    raw = ANSI_ESCAPE_RE.sub(b"", raw.rstrip(b"\r\n"))
    text = raw.decode("utf-8", "replace")
    # Keep printable Unicode and tabs.  Spell control characters out so a log
    # line cannot control a terminal or an HTML-layer log viewer.  Account for
    # bytes after expansion: 4096 NULs, for example, would otherwise become
    # 24576 bytes of ``\u0000`` text.
    pieces: list[str] = []
    used = 0
    for character in text:
        piece = (
            character
            if character == "\t" or character.isprintable()
            else "\\u%04x" % ord(character)
        )
        size = len(piece.encode("utf-8"))
        if used + size > MAX_LOG_LINE_BYTES:
            break
        pieces.append(piece)
        used += size
    return "".join(pieces)


def _log_page_fits(lines: list[str], next_cursor: int, reset: bool) -> bool:
    """Bound the encoded JSON page, not merely its pre-sanitized input."""

    payload = {
        "lines": lines,
        "nextCursor": next_cursor,
        "reset": reset,
        "truncated": True,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return len(encoded) <= MAX_LOG_PAGE_BYTES - LOG_ENVELOPE_RESERVE_BYTES


def read_log_page(path: str, cursor: int | None, limit: int) -> dict[str, Any]:
    """Read a bounded page from one already-allowlisted supervisor log.

    Cursors are byte offsets.  With no cursor the newest ``limit`` lines are
    returned.  If a log rotates and becomes smaller than a supplied cursor,
    reading restarts at byte zero and ``reset`` is true.
    """

    if cursor is not None and (not isinstance(cursor, int) or cursor < 0):
        raise ControlError("invalid_cursor", "Cursor must be a non-negative integer.", 400)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LOG_LIMIT:
        raise ControlError(
            "invalid_limit", "Limit must be between 1 and %d." % MAX_LOG_LIMIT, 400
        )

    try:
        size = Path(path).stat().st_size
        with open(path, "rb") as handle:
            if cursor is None:
                start = max(0, size - MAX_LOG_PAGE_BYTES)
                handle.seek(start)
                data = handle.read(MAX_LOG_PAGE_BYTES)
                if start:
                    first_newline = data.find(b"\n")
                    data = data[first_newline + 1 :] if first_newline >= 0 else b""
                candidates = data.splitlines()[-limit:]
                lines_reversed: list[str] = []
                for raw_line in reversed(candidates):
                    line = _sanitize_log_line(raw_line)
                    proposed = list(reversed([*lines_reversed, line]))
                    if not _log_page_fits(proposed, size, False):
                        break
                    lines_reversed.append(line)
                lines = list(reversed(lines_reversed))
                next_cursor = size
                reset = False
                truncated = start > 0 or len(data.splitlines()) > len(lines)
            else:
                reset = cursor > size
                start = 0 if reset else cursor
                handle.seek(start)
                data = handle.read(MAX_LOG_PAGE_BYTES + 1)
                page_was_capped = len(data) > MAX_LOG_PAGE_BYTES
                data = data[:MAX_LOG_PAGE_BYTES]
                split = data.splitlines(keepends=True)
                lines = []
                consumed = 0
                for raw_line in split[:limit]:
                    line = _sanitize_log_line(raw_line)
                    proposed_cursor = start + consumed + len(raw_line)
                    if not _log_page_fits([*lines, line], proposed_cursor, reset):
                        break
                    lines.append(line)
                    consumed += len(raw_line)
                next_cursor = start + consumed
                truncated = page_was_capped or len(split) > limit or next_cursor < size
    except OSError:
        raise ControlError("log_unavailable", "Service logs are unavailable.")

    return {
        "lines": lines,
        "nextCursor": next_cursor,
        "reset": reset,
        "truncated": truncated,
    }


def _run_supervisor(
    arguments: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            [SUPERVISORCTL, "-c", SUPERVISOR_CONFIG, *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            cwd="/",
            env=dict(SUPERVISOR_ENV),
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ControlError("supervisor_unavailable", "Supervisor is unavailable.")


def _supervisor_status(
    service: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> dict[str, Any]:
    service = require_service(service)
    program = MANAGED_SERVICE_PROGRAMS[service]
    proc = _run_supervisor(("status", program), runner=runner)
    if proc.returncode != 0:
        raise ControlError("supervisor_unavailable", "Supervisor status is unavailable.")
    line = next((line.strip() for line in (proc.stdout or "").splitlines() if line.strip()), "")
    parts = line.split(None, 2)
    if len(parts) < 2 or parts[0] != program:
        raise ControlError("supervisor_invalid_response", "Supervisor returned invalid status.")
    state = parts[1].upper()
    if not re.fullmatch(r"[A-Z_]{2,24}", state):
        raise ControlError("supervisor_invalid_response", "Supervisor returned invalid status.")
    payload: dict[str, Any] = {"service": service, "state": state}
    if len(parts) == 3:
        payload["detail"] = _safe_detail(parts[2])
    return payload


def helper_status(
    service: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> dict[str, Any]:
    return _supervisor_status(service, runner=runner)


def helper_restart(
    service: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> dict[str, Any]:
    service = require_service(service)
    program = MANAGED_SERVICE_PROGRAMS[service]
    proc = _run_supervisor(
        ("restart", program),
        runner=runner,
        timeout=SUPERVISOR_RESTART_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        raise ControlError("service_restart_failed", "The service could not be restarted.", 502)
    payload = _supervisor_status(service, runner=runner)
    if payload["state"] != "RUNNING":
        raise ControlError(
            "service_restart_failed",
            "The service did not return to a running state.",
            502,
        )
    payload["restarted"] = True
    return payload


def helper_set_state(
    service: str,
    running: bool,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> dict[str, Any]:
    service = require_service(service)
    action = "start" if running else "stop"
    program = MANAGED_SERVICE_PROGRAMS[service]
    timeout = SUPERVISOR_RESTART_TIMEOUT_SECONDS if running else COMMAND_TIMEOUT_SECONDS
    proc = _run_supervisor((action, program), runner=runner, timeout=timeout)
    if proc.returncode != 0:
        # Supervisor returns nonzero for an already-stopped/already-started
        # service. Re-read truth before deciding that the idempotent request failed.
        payload = _supervisor_status(service, runner=runner)
        expected = "RUNNING" if running else "STOPPED"
        if payload["state"] != expected:
            raise ControlError("service_update_failed", "The service could not be updated.", 502)
        return payload
    payload = _supervisor_status(service, runner=runner)
    expected = "RUNNING" if running else "STOPPED"
    if payload["state"] != expected:
        raise ControlError("service_update_failed", "The service did not reach the requested state.", 502)
    return payload


def helper_logs(service: str, cursor: int | None, limit: int) -> dict[str, Any]:
    service = require_service(service)
    payload = read_log_page(MANAGED_SERVICE_LOGS[service], cursor, limit)
    payload["service"] = service
    return payload
