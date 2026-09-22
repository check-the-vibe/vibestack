#!/usr/bin/env python3
"""Disposable acceptance for onboarding, browser editor, Godot, and Flatpak.

The random password is read once from stdin. It is never accepted through argv,
printed, or written to the mounted VibeStack state. This probe must only run in
the exact temporary container created by ``bin/vibestack-dev accept``.
"""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import pwd
import shlex
import signal
import stat
import subprocess
import sys
import time


PASSWORD_STATE = Path("/data/.vibestack-auth-v1/vibe.shadow")
SESSION_ENV = Path("/run/vibestack/session.env")
MAX_HTTP_RESPONSE = 1_048_576
MAX_PASSWORD_BYTES = 256
MAX_RESTORE_WAIT_SECONDS = 7200
CATALOG_COMPONENTS = ("godot", "build-essential", "flatpak")
FLATPAK_SMOKE_APP = "org.gnome.Calculator"
FLATPAK_LINK_REVIEW_APP = "org.videolan.VLC"
FLATHUB_URL = "https://dl.flathub.org/repo/"
PERSISTENT_SENTINELS = (
    (
        Path("/data/godot-config"),
        Path("/home/vibe/.config/godot"),
        ".vibestack-acceptance-config-sentinel",
        b"VibeStack acceptance: Godot config persists\n",
    ),
    (
        Path("/data/godot-data"),
        Path("/home/vibe/.local/share/godot"),
        ".vibestack-acceptance-data-sentinel",
        b"VibeStack acceptance: Godot data persists\n",
    ),
)


class AcceptanceError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def read_secret() -> bytearray:
    raw = bytearray(sys.stdin.buffer.read(MAX_PASSWORD_BYTES + 2))
    if raw.endswith(b"\n"):
        raw.pop()
    require(12 <= len(raw) <= MAX_PASSWORD_BYTES, "acceptance password is invalid")
    require(all(byte >= 0x20 and byte != 0x7F for byte in raw), "acceptance password is invalid")
    return raw


def http_json(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    timeout: float = 30,
) -> tuple[int, dict, bytes]:
    encoded = None
    headers = {"Host": "localhost"}
    # This file is created only in the disposable acceptance state. Never put
    # the credential in argv, environment variables or diagnostic output.
    with open("/data/vibestack/acceptance-owner.token", encoding="ascii") as credential_file:
        credential = credential_file.read(513).strip()
    require(32 <= len(credential) <= 512, "acceptance credential unavailable")
    headers["Authorization"] = "Bearer " + credential
    if body is not None:
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers.update(
            {
                "Content-Type": "application/json",
                "Origin": "http://localhost",
                "Sec-Fetch-Site": "same-origin",
            }
        )
    connection = http.client.HTTPConnection("127.0.0.1", 80, timeout=timeout)
    try:
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        raw = response.read(MAX_HTTP_RESPONSE + 1)
        status = response.status
    finally:
        connection.close()
    require(len(raw) <= MAX_HTTP_RESPONSE, "setup response exceeded its acceptance bound")
    try:
        payload = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError("setup returned invalid JSON") from exc
    require(isinstance(payload, dict), "setup returned a non-object response")
    return status, payload, raw


def password_status() -> bool:
    status, payload, _raw = http_json("GET", "/setup/api/state")
    require(status == 200, "setup state endpoint is unavailable")
    authentication = payload.get("authentication")
    require(isinstance(authentication, dict), "setup authentication status is absent")
    require(authentication.get("sudo_password_required") is True, "sudo policy status is wrong")
    configured = authentication.get("password_configured")
    require(isinstance(configured, bool), "password configuration status is invalid")
    return configured


def run_sudo(password: bytearray, argv: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "/usr/sbin/runuser",
            "-u",
            "vibe",
            "--",
            "/usr/bin/sudo",
            "-S",
            "-k",
            "-p",
            "",
            "--",
            *argv,
        ],
        input=bytes(password) + b"\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env={"HOME": "/root", "LANG": "C", "LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
    )


def require_sudo(password: bytearray, argv: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess:
    result = run_sudo(password, argv, timeout=timeout)
    require(result.returncode == 0, "password-authenticated sudo command failed")
    return result


def validate_persistent_hash(secret: bytearray) -> None:
    info = PASSWORD_STATE.stat(follow_symlinks=False)
    require(stat.S_ISREG(info.st_mode), "persistent password hash is not a regular file")
    require(info.st_nlink == 1, "persistent password hash has an unexpected link count")
    require((info.st_uid, info.st_gid) == (0, 0), "persistent password hash is not root-owned")
    require(stat.S_IMODE(info.st_mode) == 0o600, "persistent password hash mode is not 0600")
    stored = PASSWORD_STATE.read_bytes()
    require(stored.startswith(b"$6$rounds=656000$"), "persistent password hash format is wrong")
    require(bytes(secret) not in stored, "plaintext password reached persistent state")
    passwd = subprocess.run(
        ["/usr/bin/passwd", "--status", "vibe"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    require(passwd.returncode == 0 and passwd.stdout.split()[1:2] == [b"P"], "vibe account is not password-enabled")


def scan_logs(secret: bytearray) -> None:
    root = Path("/data/logs/vibestack")
    for directory, _names, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            path = Path(directory, filename)
            info = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                continue
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    require(bytes(secret) not in chunk, "plaintext password reached a persistent log")


def setup_state(*, timeout: float = 30) -> dict:
    status, payload, _raw = http_json("GET", "/setup/api/state", timeout=timeout)
    require(status == 200, "setup state endpoint is unavailable")
    return payload


def _validate_catalog_state(payload: dict, *, allow_running: bool) -> bool:
    require(payload.get("state_valid") is True, "saved setup state is invalid")
    require(payload.get("state_error") is None, "saved setup state reports an error")
    state = payload.get("state")
    job = payload.get("job")
    installed = payload.get("installed")
    missing = payload.get("missing")
    unknown = payload.get("unknown_selected")
    unsupported = payload.get("unsupported_selected")
    require(isinstance(state, dict), "saved setup state is absent")
    require(isinstance(job, dict), "setup restore job state is absent")
    require(
        all(isinstance(value, list) for value in (installed, missing, unknown, unsupported)),
        "setup component state is malformed",
    )
    require(
        all(
            isinstance(component, str) and component
            for values in (installed, missing, unknown, unsupported)
            for component in values
        ),
        "setup component state contains an invalid ID",
    )
    selected = state.get("selected")
    require(
        isinstance(selected, list)
        and all(isinstance(component, str) and component for component in selected),
        "saved component selection is malformed",
    )
    require(
        len(selected) == len(CATALOG_COMPONENTS)
        and set(selected) == set(CATALOG_COMPONENTS),
        "saved component selection does not contain every acceptance component",
    )
    require(state.get("completed") is True, "catalog setup was not completed")
    require(state.get("auto_restore") is True, "catalog auto-restore is disabled")
    require(not unknown, "saved component selection contains an unknown component")
    require(not unsupported, "saved component selection contains an unsupported component")
    running = job.get("running")
    require(isinstance(running, bool), "setup restore job status is malformed")
    if running:
        require(allow_running, "catalog installer is unexpectedly still running")
        return False
    require(not missing, "saved catalog components did not auto-restore")
    require(
        set(CATALOG_COMPONENTS).issubset(installed),
        "restored catalog components are not reported as installed",
    )
    return True


def wait_for_catalog_restore(timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    next_notice = 0.0
    while True:
        now = time.monotonic()
        require(now < deadline, "catalog auto-restore exceeded its acceptance timeout")
        remaining = deadline - now
        try:
            payload = setup_state(timeout=max(0.25, min(10.0, remaining)))
        except (OSError, http.client.HTTPException):
            payload = None
        if payload is not None and _validate_catalog_state(payload, allow_running=True):
            print("PASS  catalog auto-restore converged", flush=True)
            return
        now = time.monotonic()
        if now >= next_notice:
            print("WAIT  catalog components are auto-restoring", flush=True)
            next_notice = now + 30
        remaining = deadline - now
        require(remaining > 0, "catalog auto-restore exceeded its acceptance timeout")
        time.sleep(min(2.0, remaining))


def verify_catalog_components() -> None:
    sys.path.insert(0, "/usr/share/vibestack")
    import setuplib as setup_lib

    catalog = setup_lib.catalog_for_runtime(setup_lib.load_catalog())
    index = setup_lib.by_id(catalog)
    for component_id in CATALOG_COMPONENTS:
        require(component_id in index, "acceptance component is absent from the catalog")
        component = index[component_id]
        require(
            setup_lib.component_supported(component),
            "acceptance component is unsupported on this architecture",
        )
        require(
            subprocess.call(
                [
                    "/usr/sbin/runuser",
                    "-u",
                    "vibe",
                    "--",
                    "/usr/bin/env",
                    "-i",
                    "HOME=/home/vibe",
                    "USER=vibe",
                    "LOGNAME=vibe",
                    "PATH=/usr/local/bin:/usr/bin:/bin",
                    "XDG_DATA_HOME=/home/vibe/.local/share",
                    "LANG=C",
                    "LC_ALL=C",
                    "/usr/bin/bash",
                    "-c",
                    component["probe"],
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            == 0,
            f"{component_id} catalog component probe did not pass",
        )
    for executable in ("/usr/bin/gcc", "/usr/bin/g++", "/usr/bin/make"):
        require(Path(executable).is_file(), "catalog build tools are incomplete")
    _validate_catalog_state(setup_state(), allow_running=False)


def verify_legacy_browser_editor() -> None:
    service = subprocess.run(
        [
            "/usr/bin/supervisorctl",
            "-c",
            "/etc/supervisor/supervisord.conf",
            "status",
            "code-server",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )
    require(service.returncode == 0, "browser editor service is not running")
    require(b"RUNNING" in service.stdout, "browser editor service did not report RUNNING")
    page = subprocess.run(
        [
            "/usr/bin/curl",
            "--fail",
            "--location",
            "--max-time",
            "30",
            "--silent",
            "--show-error",
            "http://localhost/editor/",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=35,
        check=False,
    )
    require(page.returncode == 0, "browser editor route is unavailable")
    require(len(page.stdout) <= MAX_HTTP_RESPONSE, "browser editor response exceeded its bound")
    require(b"code-server" in page.stdout.lower(), "browser editor returned unexpected content")


# The previous VST-013 image legitimately contains the old editor during rollback.
LEGACY_UI = False

def verify_ui_migration() -> None:
    if LEGACY_UI:
        verify_legacy_browser_editor()
        return
    import shutil
    require(shutil.which("code-server") is None and shutil.which("ttyd") is None,
            "retired browser services are still installed")
    for route in ("/setup/", "/terminal/", "/editor/"):
        response = subprocess.run(
            ["curl", "--silent", "--max-time", "10", "--output", "/dev/null",
             "--write-out", "%{http_code} %{redirect_url}", "http://localhost" + route + "?force=1"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False)
        require(response.returncode == 0 and response.stdout == b"302 http://localhost/vnc/",
                "retired UI bookmark does not redirect safely")


def _persistent_directory_fd(directory: Path, home_link: Path) -> int:
    require(home_link.is_symlink(), "Godot persistent home path is not a symlink")
    require(
        os.readlink(home_link) == str(directory),
        "Godot persistent home path targets the wrong directory",
    )
    account = pwd.getpwnam("vibe")
    descriptor = os.open(
        directory,
        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    info = os.fstat(descriptor)
    try:
        require(stat.S_ISDIR(info.st_mode), "Godot persistent path is not a directory")
        require(
            (info.st_uid, info.st_gid) == (account.pw_uid, account.pw_gid),
            "Godot persistent directory is not owned by vibe",
        )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def create_persistent_sentinels() -> None:
    account = pwd.getpwnam("vibe")
    for directory, home_link, name, payload in PERSISTENT_SENTINELS:
        directory_fd = _persistent_directory_fd(directory, home_link)
        try:
            try:
                sentinel_fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError as exc:
                raise AcceptanceError("Godot persistence sentinel already exists") from exc
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(sentinel_fd, view)
                    require(written > 0, "Godot persistence sentinel write stalled")
                    view = view[written:]
                os.fchown(sentinel_fd, account.pw_uid, account.pw_gid)
                os.fchmod(sentinel_fd, 0o600)
                os.fsync(sentinel_fd)
            finally:
                os.close(sentinel_fd)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    verify_persistent_sentinels()


def verify_persistent_sentinels() -> None:
    account = pwd.getpwnam("vibe")
    for directory, home_link, name, payload in PERSISTENT_SENTINELS:
        directory_fd = _persistent_directory_fd(directory, home_link)
        try:
            sentinel_fd = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            try:
                info = os.fstat(sentinel_fd)
                require(stat.S_ISREG(info.st_mode), "Godot persistence sentinel is not regular")
                require(info.st_nlink == 1, "Godot persistence sentinel has extra links")
                require(
                    (info.st_uid, info.st_gid) == (account.pw_uid, account.pw_gid),
                    "Godot persistence sentinel is not owned by vibe",
                )
                require(
                    stat.S_IMODE(info.st_mode) == 0o600,
                    "Godot persistence sentinel mode is not 0600",
                )
                require(
                    os.read(sentinel_fd, len(payload) + 1) == payload,
                    "Godot persistence sentinel content changed",
                )
            finally:
                os.close(sentinel_fd)
        finally:
            os.close(directory_fd)


def configure(secret: bytearray) -> None:
    require(not password_status(), "fresh acceptance account unexpectedly has a password")
    before = subprocess.run(
        ["/usr/bin/passwd", "--status", "vibe"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    require(before.returncode == 0 and before.stdout.split()[1:2] == [b"L"], "fresh vibe account is not locked")

    password_text = bytes(secret).decode("ascii", "strict")
    status, payload, raw = http_json(
        "POST",
        "/setup/api/password",
        {"password": password_text, "confirmation": password_text},
    )
    require(status == 200, "password endpoint rejected a valid request")
    require(payload.get("authentication", {}).get("password_configured") is True, "password endpoint returned the wrong status")
    require(bytes(secret) not in raw, "password endpoint echoed plaintext")
    validate_persistent_hash(secret)
    native_vnc = subprocess.run(
        [
            "/usr/bin/supervisorctl",
            "-c",
            "/etc/supervisor/supervisord.conf",
            "status",
            "native-vnc",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )
    require(
        native_vnc.returncode == 0 and b"RUNNING" in native_vnc.stdout,
        "native VNC did not start after the first Linux password was configured",
    )

    wrong = bytearray(b"definitely-not-the-acceptance-password\n" * 3)
    rejected = run_sudo(wrong, ["/usr/bin/id", "-u"], timeout=30)
    for index in range(len(wrong)):
        wrong[index] = 0
    require(rejected.returncode != 0, "sudo accepted an incorrect password")

    identity = require_sudo(secret, ["/usr/bin/id", "-u"], timeout=30)
    require(identity.stdout.strip() == b"0", "password-authenticated sudo did not become root")
    require_sudo(
        secret,
        ["/usr/bin/env", "DEBIAN_FRONTEND=noninteractive", "/usr/bin/apt-get", "update"],
        timeout=900,
    )
    require_sudo(
        secret,
        [
            "/usr/bin/env",
            "DEBIAN_FRONTEND=noninteractive",
            "/usr/bin/apt-get",
            "install",
            "-y",
            "--no-install-recommends",
            "build-essential",
        ],
        timeout=900,
    )
    for executable in ("/usr/bin/gcc", "/usr/bin/g++", "/usr/bin/make"):
        require(Path(executable).is_file(), "sudo apt did not install the native toolchain")
    scan_logs(secret)


def verify_restored(secret: bytearray) -> None:
    require(password_status(), "password status was not restored in the replacement container")
    validate_persistent_hash(secret)
    identity = require_sudo(secret, ["/usr/bin/id", "-u"], timeout=30)
    require(identity.stdout.strip() == b"0", "restored password does not authenticate sudo")
    package = subprocess.run(
        ["/usr/bin/dpkg-query", "-W", "-f=${db:Status-Abbrev}", "build-essential"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    require(package.returncode != 0 or package.stdout != b"ii ", "ad-hoc apt package survived image replacement")
    scan_logs(secret)


def load_session_environment() -> dict[str, str]:
    environment = {
        "HOME": "/home/vibe",
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }
    for raw_line in SESSION_ENV.read_text(encoding="utf-8").splitlines():
        require(raw_line.startswith("export "), "session environment has an unexpected line")
        tokens = shlex.split(raw_line[len("export ") :], posix=True)
        require(len(tokens) == 1 and "=" in tokens[0], "session environment is malformed")
        key, value = tokens[0].split("=", 1)
        require(key in {
            "DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "XDG_CURRENT_DESKTOP",
            "XDG_SESSION_TYPE", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
            "XDG_DATA_DIRS",
            "DBUS_SESSION_BUS_ADDRESS", "GNOME_KEYRING_CONTROL",
        }, "session environment contains an unexpected key")
        environment[key] = value
    return environment


def verify_godot() -> None:
    binary = Path("/usr/local/bin/godot")
    desktop_entry = Path("/usr/share/applications/org.godotengine.Godot.desktop")
    commit_marker = Path("/usr/local/bin/.vibestack-godot-4.7.2.complete")
    require(binary.is_file() and os.access(binary, os.X_OK), "Godot binary is not installed")
    require(desktop_entry.is_file(), "Godot desktop entry is not installed")
    require(
        commit_marker.is_file()
        and commit_marker.read_text(encoding="utf-8") == "godot 4.7.2\n",
        "Godot publication did not commit",
    )
    version = subprocess.run(
        [str(binary), "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
        env={"HOME": "/tmp", "LANG": "C", "PATH": "/usr/local/bin:/usr/bin:/bin"},
    )
    require(version.returncode == 0 and version.stdout.startswith(b"4.7.2.stable.official."), "Godot version is not the pinned stable release")

    project = Path("/tmp/vibestack-godot-acceptance")
    project.mkdir(mode=0o700, exist_ok=False)
    (project / "project.godot").write_text(
        '[application]\nconfig/name="VibeStack acceptance"\n'
        '[display]\nwindow/size/viewport_width=640\nwindow/size/viewport_height=480\n'
        '[rendering]\nrenderer/rendering_method="gl_compatibility"\n',
        encoding="utf-8",
    )
    os.chown(project, 1000, 1000)
    os.chown(project / "project.godot", 1000, 1000)
    environment = load_session_environment()
    process = subprocess.Popen(
        [
            "/usr/sbin/runuser", "--preserve-environment", "-u", "vibe", "--",
            str(binary), "--editor", "--path", str(project),
            "--rendering-method", "gl_compatibility", "--audio-driver", "Dummy",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=environment,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 60
        found = False
        while time.monotonic() < deadline:
            require(process.poll() is None, "Godot exited before presenting its editor window")
            windows = subprocess.run(
                ["/usr/bin/wmctrl", "-lx"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                env=environment,
            )
            if windows.returncode == 0 and b"godot" in windows.stdout.lower():
                found = True
                break
            time.sleep(1)
        require(found, "Godot did not present an XFCE editor window")
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)


def _run_as_vibe(argv: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "/usr/sbin/runuser", "--preserve-environment", "-u", "vibe", "--",
            *argv,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=load_session_environment(),
    )


def _run_as_vibe_with_input(
    argv: list[str], input_bytes: bytes, *, timeout: int = 120
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "/usr/sbin/runuser", "--preserve-environment", "-u", "vibe", "--",
            *argv,
        ],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=load_session_environment(),
    )


def verify_flatpak() -> None:
    marker = Path("/run/vibestack/host/flatpak-enabled")
    marker_info = marker.stat(follow_symlinks=False)
    require(stat.S_ISREG(marker_info.st_mode), "Flatpak capability marker is not regular")
    require(marker_info.st_nlink == 1, "Flatpak capability marker has extra links")
    require(
        (marker_info.st_uid, marker_info.st_gid) == (0, 0),
        "Flatpak capability marker is not root-owned",
    )
    require(
        stat.S_IMODE(marker_info.st_mode) == 0o444,
        "Flatpak capability marker mode is not 0444",
    )
    for path in (
        Path("/usr/bin/flatpak"),
        Path("/usr/bin/bwrap"),
        Path("/usr/local/bin/vibestack-flatpak"),
    ):
        require(path.is_file() and os.access(path, os.X_OK), "Flatpak tooling is incomplete")
    package = subprocess.run(
        [
            "/usr/bin/dpkg-query", "-W", "-f=${db:Status-Abbrev}",
            "xdg-desktop-portal-xapp",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    require(package.returncode == 0 and package.stdout == b"ii ", "XFCE portal backend is absent")

    persistent_paths = (
        (Path("/data/flatpak"), Path("/home/vibe/.local/share/flatpak")),
        (Path("/data/flatpak-apps"), Path("/home/vibe/.var/app")),
    )
    for directory, home_link in persistent_paths:
        require(home_link.is_symlink(), "Flatpak persistent home path is not a symlink")
        require(os.readlink(home_link) == str(directory), "Flatpak state targets the wrong directory")
        info = directory.stat(follow_symlinks=False)
        require(stat.S_ISDIR(info.st_mode), "Flatpak persistent path is not a directory")
        account = pwd.getpwnam("vibe")
        require(
            (info.st_uid, info.st_gid) == (account.pw_uid, account.pw_gid),
            "Flatpak persistent path is not owned by vibe",
        )

    environment = load_session_environment()
    data_dirs = environment.get("XDG_DATA_DIRS", "").split(":")
    require(
        "/home/vibe/.local/share/flatpak/exports/share" in data_dirs,
        "Flatpak application exports are absent from XDG_DATA_DIRS",
    )
    sandbox = _run_as_vibe(["/usr/local/bin/vibestack-flatpak", "check"])
    require(sandbox.returncode == 0, "nested Flatpak sandbox check failed")
    remotes = _run_as_vibe(
        ["/usr/bin/flatpak", "--user", "remotes", "--columns=name,url"]
    )
    require(remotes.returncode == 0, "Flatpak remote listing failed")
    configured = {
        fields[0]: fields[1]
        for line in remotes.stdout.decode("utf-8", "strict").splitlines()
        if len(fields := line.split()) >= 2
    }
    require(configured.get("flathub") == FLATHUB_URL, "stable Flathub URL is not exact")
    mime_handler = _run_as_vibe(
        [
            "/usr/bin/xdg-mime", "query", "default",
            "application/vnd.flatpak.ref",
        ]
    )
    require(
        mime_handler.returncode == 0
        and mime_handler.stdout.strip() == b"vibestack-flatpakref.desktop",
        "stable Flathub reference handler is not the desktop default",
    )
    handler = Path("/usr/share/applications/vibestack-flatpakref.desktop")
    require(handler.is_file(), "Flatpak reference desktop handler is absent")
    handler_text = handler.read_text(encoding="utf-8")
    require(
        "MimeType=application/vnd.flatpak.ref;" in handler_text
        and "flatpak-ref %f" in handler_text,
        "Flatpak reference desktop handler is malformed",
    )
    url_mime_handler = _run_as_vibe(
        [
            "/usr/bin/xdg-mime", "query", "default",
            "x-scheme-handler/flatpak+https",
        ]
    )
    require(
        url_mime_handler.returncode == 0
        and url_mime_handler.stdout.strip() == b"vibestack-flatpak-url.desktop",
        "stable Flathub install-link handler is not the desktop default",
    )
    url_handler = Path("/usr/share/applications/vibestack-flatpak-url.desktop")
    require(url_handler.is_file(), "Flatpak install-link desktop handler is absent")
    url_handler_text = url_handler.read_text(encoding="utf-8")
    require(
        "MimeType=x-scheme-handler/flatpak+https;" in url_handler_text
        and "flatpak-url %u" in url_handler_text,
        "Flatpak install-link desktop handler is malformed",
    )
    search = _run_as_vibe(
        ["/usr/local/bin/vibestack-flatpak", "search", FLATPAK_SMOKE_APP],
        timeout=300,
    )
    require(
        search.returncode == 0 and FLATPAK_SMOKE_APP.encode() in search.stdout,
        "stable Flathub search did not return the smoke application",
    )
    link_review = _run_as_vibe_with_input(
        [
            "/usr/local/bin/vibestack-flatpak",
            "install-url",
            (
                "flatpak+https://dl.flathub.org/repo/appstream/"
                f"{FLATPAK_LINK_REVIEW_APP}.flatpakref"
            ),
        ],
        b"n\n",
        timeout=300,
    )
    link_review_output = link_review.stdout + link_review.stderr
    require(link_review.returncode != 0, "cancelled Flatpak link review installed an app")
    require(
        f"Validated stable Flathub install link for {FLATPAK_LINK_REVIEW_APP}.".encode()
        in link_review_output,
        "stable Flathub install link did not reach the validated review flow",
    )
    require(b"[Context]" in link_review_output, "Flatpak link review omitted permissions")
    require(b"unknown option" not in link_review_output.lower(), "Flatpak review used an unsupported option")
    installed = _run_as_vibe(
        ["/usr/bin/flatpak", "--user", "info", FLATPAK_SMOKE_APP]
    )
    require(installed.returncode == 0, "disposable Flatpak smoke app is not installed")

    process = subprocess.Popen(
        [
            "/usr/sbin/runuser", "--preserve-environment", "-u", "vibe", "--",
            "/usr/local/bin/vibestack-flatpak", "run", FLATPAK_SMOKE_APP,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=environment,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 90
        found = False
        while time.monotonic() < deadline:
            require(process.poll() is None, "Flatpak smoke app exited before opening")
            windows = subprocess.run(
                ["/usr/bin/wmctrl", "-lx"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                env=environment,
            )
            if windows.returncode == 0 and b"calculator" in windows.stdout.lower():
                found = True
                break
            time.sleep(1)
        require(found, "Flatpak smoke app did not present an XFCE window")
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)


def verify_initial_catalog_install() -> None:
    verify_catalog_components()
    verify_ui_migration()
    create_persistent_sentinels()
    verify_godot()
    verify_flatpak()


def verify_restored_catalog(secret: bytearray, timeout_seconds: int) -> None:
    wait_for_catalog_restore(timeout_seconds)
    require(password_status(), "password status was lost during catalog restoration")
    validate_persistent_hash(secret)
    identity = require_sudo(secret, ["/usr/bin/id", "-u"], timeout=30)
    require(identity.stdout.strip() == b"0", "restored password no longer authenticates sudo")
    verify_catalog_components()
    verify_ui_migration()
    verify_persistent_sentinels()
    verify_godot()
    verify_flatpak()
    scan_logs(secret)


def parse_restore_timeout(raw: str) -> int:
    require(raw.isascii() and raw.isdecimal(), "invalid catalog restore timeout")
    timeout_seconds = int(raw, 10)
    require(
        60 <= timeout_seconds <= MAX_RESTORE_WAIT_SECONDS,
        "invalid catalog restore timeout",
    )
    return timeout_seconds


def main() -> int:
    global CATALOG_COMPONENTS, LEGACY_UI
    require(os.geteuid() == 0, "runtime onboarding acceptance must run as root")
    require(len(sys.argv) >= 2, "invalid acceptance mode")
    mode = sys.argv[1]
    if mode == "catalog-installed":
        require(len(sys.argv) == 2, "invalid acceptance mode")
        verify_initial_catalog_install()
        print("PASS  catalog probes, UI migration, and real Godot/Flatpak XFCE launches")
        return 0
    require(
        (mode in {"configure", "verify-restored"} and len(sys.argv) == 2)
        or (mode == "verify-catalog-restored" and 3 <= len(sys.argv) <= 5
            and len(set(sys.argv[3:])) == len(sys.argv[3:])
            and set(sys.argv[3:]) <= {"with-providers", "with-legacy-ui"}),
        "invalid acceptance mode",
    )
    if "with-providers" in sys.argv[3:]:
        CATALOG_COMPONENTS += ("node", "codex-cli", "opencode")
    LEGACY_UI = "with-legacy-ui" in sys.argv[3:]

    secret = read_secret()
    try:
        if mode == "configure":
            configure(secret)
            print("PASS  onboarding password API and real sudo apt install")
        elif mode == "verify-restored":
            verify_restored(secret)
            print("PASS  onboarding password restore and ephemeral apt boundary")
        else:
            verify_restored_catalog(secret, parse_restore_timeout(sys.argv[2]))
            print("PASS  restored catalog, UI migration, Godot/Flatpak GUI state, and Linux password")
    finally:
        for index in range(len(secret)):
            secret[index] = 0
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AcceptanceError, OSError, subprocess.SubprocessError) as error:
        print(f"FAIL  onboarding runtime acceptance: {error}", file=sys.stderr)
        raise SystemExit(1)
