"""Shared state, catalog and probe helpers for the VibeStack setup wizard."""

import copy
import json
import os
import platform
import re
import secrets
import stat
import subprocess
import time
from contextlib import contextmanager

import fcntl

CATALOG_PATH = os.environ.get("VIBESTACK_CATALOG", "/usr/share/vibestack/catalog.json")
HOME = os.path.expanduser("~")
# Use the canonical persistent directory directly. In the runtime image,
# ~/.vibestack is intentionally a convenience symlink to this directory and
# must not be followed by the state store's O_NOFOLLOW root open.
STATE_DIR = os.environ.get("VIBESTACK_STATE_DIR", "/data/vibestack")
STATE_PATH = os.path.join(STATE_DIR, "setup.json")
STATE_LOCK_NAME = ".setup.lock"
INSTALL_JOB_LOCK_NAME = ".setup-job.lock"
STATE_VERSION = 1
STATE_MAX_BYTES = 64 * 1024
STATE_MAX_COMPONENTS = 256
STATE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
STATE_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
STATE_KEYS = frozenset(
    {"version", "completed", "completed_at", "selected", "skipped", "auto_restore"}
)
SUPPORTED_ARCHITECTURES = ("amd64", "arm64")
SUPPORTED_RUNTIME_REQUIREMENTS = ("nested-sandbox",)
FLATPAK_CAPABILITY_MARKER = "/run/vibestack/host/flatpak-enabled"
ARCHITECTURE_ALIASES = {
    "amd64": "amd64",
    "x86_64": "amd64",
    "x86-64": "amd64",
    "arm64": "arm64",
    "aarch64": "arm64",
}
RUNTIME_REQUIREMENT_REASONS = {
    "nested-sandbox": (
        "Unavailable until VibeStack is started with --flatpak, which enables "
        "the nested namespaces and mounts required by application sandboxes."
    ),
}


class StateError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate state key")
        result[key] = value
    return result


def load_catalog():
    with open(CATALOG_PATH) as fh:
        return json.load(fh)


def current_architecture(machine=None):
    value = platform.machine() if machine is None else machine
    normalized = str(value).strip().lower()
    return ARCHITECTURE_ALIASES.get(normalized, normalized or "unknown")


def component_supported(component, architecture=None):
    supported = component.get("supported")
    if isinstance(supported, bool) and architecture is None:
        return supported
    host_architecture = current_architecture(architecture)
    architectures = component.get("architectures", SUPPORTED_ARCHITECTURES)
    return (
        isinstance(architectures, (list, tuple))
        and all(item in SUPPORTED_ARCHITECTURES for item in architectures)
        and host_architecture in architectures
    )


def current_runtime_capabilities():
    capabilities = set()
    try:
        marker = os.stat(FLATPAK_CAPABILITY_MARKER, follow_symlinks=False)
    except OSError:
        marker = None
    if (
        marker is not None
        and stat.S_ISREG(marker.st_mode)
        and marker.st_nlink == 1
        and (marker.st_uid, marker.st_gid) == (0, 0)
        and stat.S_IMODE(marker.st_mode) == 0o444
    ):
        capabilities.add("nested-sandbox")
    return frozenset(capabilities)


def catalog_for_runtime(catalog, architecture=None, runtime_capabilities=None):
    """Return a UI/API catalog annotated for the current machine."""

    architecture = current_architecture(architecture)
    if runtime_capabilities is None:
        runtime_capabilities = current_runtime_capabilities()
    else:
        runtime_capabilities = frozenset(runtime_capabilities)
    result = copy.deepcopy(catalog)
    result["architecture"] = architecture
    result["runtime_capabilities"] = sorted(runtime_capabilities)
    components = result.get("components", [])
    index = {component.get("id"): component for component in components}
    for component in components:
        architectures = component.get("architectures", list(SUPPORTED_ARCHITECTURES))
        requirements = component.get("runtime_requirements", [])
        valid_requirements = (
            isinstance(requirements, list)
            and all(
                isinstance(item, str) and item in SUPPORTED_RUNTIME_REQUIREMENTS
                for item in requirements
            )
        )
        missing_requirements = (
            [item for item in requirements if item not in runtime_capabilities]
            if valid_requirements
            else ["invalid"]
        )
        architecture_supported = component_supported(component, architecture)
        supported = architecture_supported and not missing_requirements
        component["supported"] = supported
        if not architecture_supported:
            names = ", ".join(architectures) if isinstance(architectures, list) else "none"
            component["support_reason"] = (
                "Unavailable on %s; supported architectures: %s."
                % (architecture, names)
            )
        elif missing_requirements:
            component["support_reason"] = " ".join(
                RUNTIME_REQUIREMENT_REASONS.get(
                    requirement,
                    "Unavailable because this component has an unsupported runtime requirement.",
                )
                for requirement in missing_requirements
            )
        elif supported:
            component["support_reason"] = "Supported on %s." % architecture

    # A component cannot be offered when one of its dependencies is not
    # available on this architecture, even if its own artifact is portable.
    changed = True
    while changed:
        changed = False
        for component in components:
            if not component.get("supported"):
                continue
            unavailable = [
                dependency
                for dependency in component.get("requires", [])
                if dependency not in index or not index[dependency].get("supported")
            ]
            if unavailable:
                component["supported"] = False
                component["support_reason"] = (
                    "Unavailable because required component(s) are unsupported: %s."
                    % ", ".join(unavailable)
                )
                changed = True

    for preset in result.get("presets", []):
        configured = list(preset.get("components", []))
        preset["components"] = [
            component_id
            for component_id in configured
            if component_id in index and index[component_id].get("supported")
        ]
        preset["unsupported_components"] = [
            component_id
            for component_id in configured
            if component_id in index and not index[component_id].get("supported")
        ]
    return result


def by_id(catalog):
    return {c["id"]: c for c in catalog["components"]}


def default_state():
    return {
        "version": STATE_VERSION,
        "completed": False,
        "completed_at": None,
        "selected": [],
        "skipped": False,
        "auto_restore": True,
    }


def _state_name():
    state_dir = os.path.abspath(STATE_DIR)
    state_path = os.path.abspath(STATE_PATH)
    if os.path.dirname(state_path) != state_dir:
        raise StateError(
            "state_unreadable", "The saved setup state path is not safely configured."
        )
    name = os.path.basename(state_path)
    if name in ("", ".", "..") or "/" in name:
        raise StateError(
            "state_unreadable", "The saved setup state path is not safely configured."
        )
    return name


def _state_error(message, exc=None):
    error = StateError("state_unreadable", message)
    if exc is not None:
        error.__cause__ = exc
    return error


def _validate_state_directory(directory_fd):
    info = os.fstat(directory_fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise _state_error("The saved setup state directory failed a safety check.")


def _validate_lock_file(lock_fd, directory_fd, name):
    info = os.fstat(lock_fd)
    try:
        current = os.stat(
            name, dir_fd=directory_fd, follow_symlinks=False
        )
    except OSError as exc:
        raise _state_error("The setup state lock cannot be verified.", exc)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)
    ):
        raise _state_error("The setup state lock failed a safety check.")


def _open_state_directory():
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    directory_fd = os.open(
        STATE_DIR,
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        _validate_state_directory(directory_fd)
    except BaseException:
        os.close(directory_fd)
        raise
    return directory_fd


def _open_lock_file(directory_fd, name):
    lock_fd = os.open(
        name,
        os.O_RDWR
        | os.O_CREAT
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
        0o600,
        dir_fd=directory_fd,
    )
    try:
        _validate_lock_file(lock_fd, directory_fd, name)
        os.fchmod(lock_fd, 0o600)
    except BaseException:
        os.close(lock_fd)
        raise
    return lock_fd


@contextmanager
def _state_lock():
    """Hold the cross-process lock for one complete state transaction."""

    directory_fd = -1
    lock_fd = -1
    try:
        directory_fd = _open_state_directory()
        lock_fd = _open_lock_file(directory_fd, STATE_LOCK_NAME)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _validate_lock_file(lock_fd, directory_fd, STATE_LOCK_NAME)
        if stat.S_IMODE(os.fstat(lock_fd).st_mode) != 0o600:
            raise _state_error("The setup state lock has unsafe permissions.")
        yield directory_fd
    except StateError:
        raise
    except OSError as exc:
        raise _state_error("The saved setup state cannot be locked safely.", exc)
    finally:
        if lock_fd >= 0:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def acquire_install_job_lock(*, blocking=False):
    """Acquire the lease held across installer execution and state commit."""

    directory_fd = -1
    lock_fd = -1
    try:
        directory_fd = _open_state_directory()
        lock_fd = _open_lock_file(directory_fd, INSTALL_JOB_LOCK_NAME)
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(lock_fd, operation)
        except BlockingIOError:
            # The failed flock does not grant this descriptor ownership of the
            # lease. Revalidate the directory entry before reporting a normal
            # busy state so a concurrent replacement remains fail-closed.
            _validate_lock_file(lock_fd, directory_fd, INSTALL_JOB_LOCK_NAME)
            if stat.S_IMODE(os.fstat(lock_fd).st_mode) != 0o600:
                raise _state_error("The setup installer lock has unsafe permissions.")
            raise StateError(
                "job_running", "A setup installer job is already running."
            ) from None
        _validate_lock_file(lock_fd, directory_fd, INSTALL_JOB_LOCK_NAME)
        if stat.S_IMODE(os.fstat(lock_fd).st_mode) != 0o600:
            raise _state_error("The setup installer lock has unsafe permissions.")
        return lock_fd
    except StateError:
        if lock_fd >= 0:
            os.close(lock_fd)
        raise
    except OSError as exc:
        if lock_fd >= 0:
            os.close(lock_fd)
        raise _state_error("The setup installer lock cannot be opened safely.", exc)
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def install_job_lock_held():
    """Return whether another open description currently owns the job lease.

    A separate descriptor is deliberately used even when the caller is the
    setup service. On Linux, flock ownership belongs to an open file
    description, so a failed nonblocking acquisition observes both CLI-held
    and service-held leases without acquiring or releasing either one.
    """

    directory_fd = -1
    lock_fd = -1
    acquired = False
    try:
        directory_fd = _open_state_directory()
        lock_fd = _open_lock_file(directory_fd, INSTALL_JOB_LOCK_NAME)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            _validate_lock_file(lock_fd, directory_fd, INSTALL_JOB_LOCK_NAME)
            if stat.S_IMODE(os.fstat(lock_fd).st_mode) != 0o600:
                raise _state_error("The setup installer lock has unsafe permissions.")
            return True
        _validate_lock_file(lock_fd, directory_fd, INSTALL_JOB_LOCK_NAME)
        if stat.S_IMODE(os.fstat(lock_fd).st_mode) != 0o600:
            raise _state_error("The setup installer lock has unsafe permissions.")
        return False
    except StateError:
        raise
    except OSError as exc:
        raise _state_error("The setup installer lock cannot be inspected safely.", exc)
    finally:
        if lock_fd >= 0:
            try:
                if acquired:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def release_install_job_lock(lock_fd):
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


@contextmanager
def install_job_lock(*, blocking=False):
    lock_fd = acquire_install_job_lock(blocking=blocking)
    try:
        yield
    finally:
        release_install_job_lock(lock_fd)


def _load_state_locked(directory_fd):
    state_name = _state_name()
    # O_NONBLOCK prevents a substituted FIFO from hanging setup before fstat
    # has a chance to reject every non-regular state leaf.
    flags = (
        os.O_RDONLY
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        fd = os.open(state_name, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        return default_state()
    except OSError as exc:
        raise StateError(
            "state_unreadable", "The saved setup state cannot be read safely."
        ) from exc
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or before.st_size > STATE_MAX_BYTES
        ):
            raise StateError(
                "state_unreadable", "The saved setup state failed a safety check."
            )
        chunks = []
        remaining = STATE_MAX_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise StateError(
                "state_unreadable", "The saved setup state changed while it was read."
            )
    finally:
        os.close(fd)
    try:
        state = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite state number")
            ),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise StateError(
            "state_invalid", "The saved setup state is not valid JSON."
        ) from exc
    _validate_state(state)
    # This former optional component is now supplied by every base image.
    # Read legacy selections without rewriting or invalidating unrelated state.
    state["selected"] = [item for item in state["selected"] if item != "browser-editor"]
    return state


def load_state():
    with _state_lock() as directory_fd:
        return _load_state_locked(directory_fd)


def _validate_state(state):
    if not isinstance(state, dict) or set(state) != STATE_KEYS:
        raise StateError(
            "state_invalid", "The saved setup state has invalid or missing fields."
        )
    version = state["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != STATE_VERSION:
        raise StateError(
            "state_version_unsupported",
            "The saved setup state version is not supported by this image.",
        )
    completed = state["completed"]
    completed_at = state["completed_at"]
    selected = state["selected"]
    skipped = state["skipped"]
    auto_restore = state["auto_restore"]
    if (
        not isinstance(completed, bool)
        or not isinstance(skipped, bool)
        or not isinstance(auto_restore, bool)
        or not isinstance(selected, list)
        or len(selected) > STATE_MAX_COMPONENTS
        or any(not isinstance(item, str) or not STATE_ID_RE.fullmatch(item) for item in selected)
        or len(set(selected)) != len(selected)
        or selected != sorted(selected)
    ):
        raise StateError("state_invalid", "The saved setup state has invalid values.")
    if completed:
        if not isinstance(completed_at, str) or not STATE_TIMESTAMP_RE.fullmatch(completed_at):
            raise StateError(
                "state_invalid", "The saved setup completion timestamp is invalid."
            )
        try:
            time.strptime(completed_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise StateError(
                "state_invalid", "The saved setup completion timestamp is invalid."
            ) from exc
    elif completed_at is not None or skipped:
        raise StateError("state_invalid", "The saved setup completion state is inconsistent.")
    if skipped and selected:
        raise StateError("state_invalid", "A skipped setup state cannot select components.")


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short state write")
        view = view[written:]


def _write_state_locked(directory_fd, state):
    state_name = _state_name()
    encoded = (
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if len(encoded) > STATE_MAX_BYTES:
        raise StateError("state_invalid", "The saved setup state is too large.")

    tmp_name = None
    tmp_fd = -1
    try:
        for _attempt in range(16):
            candidate = ".setup-%s.tmp" % secrets.token_hex(16)
            try:
                tmp_fd = os.open(
                    candidate,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | os.O_CLOEXEC
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            tmp_name = candidate
            break
        if tmp_name is None:
            raise OSError("could not allocate a unique setup state temporary file")
        os.fchmod(tmp_fd, 0o600)
        _write_all(tmp_fd, encoded)
        os.fsync(tmp_fd)
        os.close(tmp_fd)
        tmp_fd = -1
        os.replace(
            tmp_name,
            state_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        tmp_name = None
        os.fsync(directory_fd)
    except StateError:
        raise
    except OSError as exc:
        raise _state_error("The saved setup state could not be written safely.", exc)
    finally:
        if tmp_fd >= 0:
            os.close(tmp_fd)
        if tmp_name is not None:
            try:
                os.unlink(tmp_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def _save_changes_locked(directory_fd, changes):
    state = _load_state_locked(directory_fd)
    state.update(changes)
    state["version"] = STATE_VERSION
    _validate_state(state)
    _write_state_locked(directory_fd, state)
    return state


def save_state(**changes):
    with _state_lock() as directory_fd:
        return _save_changes_locked(directory_fd, changes)


def clear_state():
    with _state_lock() as directory_fd:
        try:
            os.unlink(_state_name(), dir_fd=directory_fd)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _state_error("The saved setup state could not be cleared safely.", exc)
        os.fsync(directory_fd)
        return True


def mark_complete(selected, skipped=False):
    return save_state(
        completed=True,
        completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        selected=sorted(set(selected)),
        skipped=skipped,
    )


def record_install_outcome(requested, installed, command_succeeded):
    """Persist an install result without losing work that still needs recovery.

    A request is complete only when the installer succeeded *and* every saved
    selection passes its catalog probe.  On failure the full requested set is
    retained, while the prior completion state is left unchanged.  This means
    first-run failures keep the wizard pending and failures while adding to an
    already-configured machine remain eligible for auto-restore.
    """
    with _state_lock() as directory_fd:
        previous = _load_state_locked(directory_fd)
        previous_selected = previous.get("selected", [])
        selected = sorted(
            set(previous_selected)
            | {item for item in requested if isinstance(item, str)}
        )
        installed_set = {item for item in installed if isinstance(item, str)}
        converged = bool(command_succeeded) and all(
            item in installed_set for item in selected
        )
        if converged:
            changes = {
                "completed": True,
                "completed_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
                "selected": selected,
                "skipped": False,
            }
        else:
            changes = {"selected": selected, "skipped": False}
        return _save_changes_locked(directory_fd, changes), converged


def is_installed(component):
    """Run the component's probe command. Non-zero exit means not installed."""
    return subprocess.call(
        ["bash", "-c", component["probe"]],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) == 0


def installed_ids(catalog):
    return [
        component["id"]
        for component in catalog["components"]
        if component_supported(component) and is_installed(component)
    ]


def resolve(catalog, ids):
    """Expand requires and return ids in install order, catalog order as tiebreak."""
    index = by_id(catalog)
    order = [c["id"] for c in catalog["components"]]
    seen, out = set(), []

    def visit(cid, chain=()):
        if cid in seen or cid not in index:
            return
        if cid in chain:  # cycle in the catalog; stop rather than recurse
            return
        for dep in index[cid].get("requires", []):
            visit(dep, chain + (cid,))
        if cid not in seen:
            seen.add(cid)
            out.append(cid)

    for cid in sorted(ids, key=lambda i: order.index(i) if i in order else 99):
        visit(cid)
    return out


def missing_for_state(catalog, state):
    index = by_id(catalog)
    return [
        cid
        for cid in state.get("selected", [])
        if (
            cid not in index
            or not component_supported(index[cid])
            or not is_installed(index[cid])
        )
    ]


def restorable_missing_for_state(catalog, state):
    index = by_id(catalog)
    return [
        cid
        for cid in state.get("selected", [])
        if (
            cid in index
            and component_supported(index[cid])
            and not is_installed(index[cid])
        )
    ]


def unknown_for_state(catalog, state):
    known = set(by_id(catalog))
    return [cid for cid in state.get("selected", []) if cid not in known]


def unsupported_for_state(catalog, state):
    index = by_id(catalog)
    return [
        cid
        for cid in state.get("selected", [])
        if cid in index and not component_supported(index[cid])
    ]
