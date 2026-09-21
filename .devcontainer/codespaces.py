#!/usr/bin/env python3
"""Build and resume the private VibeStack desktop inside a Codespace."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "vibestack:codespaces"
CONTAINER = "vibestack-codespaces"
RUNTIME = Path("/vibestack-runtime")


def read_metadata(path):
    """Read only small, ordinary lifecycle markers; never follow links or block."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
            raise RuntimeError("Unsafe runtime storage metadata")
        value = source.read(4097)
        if len(value) > 4096:
            raise RuntimeError("Oversized runtime storage metadata")
        return value.decode("utf-8", errors="strict").strip()


def write_metadata(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as target:
        target.write(value + "\n")
        target.flush()
        os.fsync(target.fileno())


def runtime_state():
    """Keep root-private desktop files outside the platform's workspace tree.

    A non-secret witness in /workspaces detects an unexpectedly empty/different
    runtime volume. Never mistake lost storage for a new first boot.
    """
    if RUNTIME.is_symlink() or not RUNTIME.is_mount():
        raise RuntimeError("Persistent runtime volume is missing; rebuild the Dev Container")
    state = RUNTIME / ROOT.name
    legacy = ROOT.parent / ".vibestack-codespaces" / ROOT.name
    witness = legacy / "runtime-volume-id"
    identity = state / ".volume-id"
    if any(path.is_symlink() for path in (state, legacy.parent, legacy, witness, identity)):
        raise RuntimeError("Runtime storage metadata must not contain symlinks")
    expected = read_metadata(witness)
    if expected is not None:
        actual = read_metadata(identity)
        if len(expected) != 32 or any(c not in "0123456789abcdef" for c in expected) or actual != expected:
            raise RuntimeError("Runtime volume identity changed; restore the existing volume instead of resetting state")
    else:
        if os.path.lexists(legacy / "data"):
            raise RuntimeError("Existing workspace-backed state needs explicit migration; follow .context/github-codespaces.md")
        if state.exists() and any(state.iterdir()):
            raise RuntimeError("Unrecognized runtime state; inspect it before adoption")
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        legacy.mkdir(mode=0o700, parents=True, exist_ok=True)
        value = secrets.token_hex(16)
        # Exclusive creation preserves existing metadata and fails on races.
        write_metadata(identity, value)
        write_metadata(witness, value)
    return state


def migrated_existing(value, data, projects, host):
    """A checked copy may deliberately replace the old workspace-backed bind.

    The original data remains intact for rollback. No ownership adoption occurs.
    """
    legacy = ROOT.parent / ".vibestack-codespaces" / ROOT.name
    marker = data.parent / ".migrated-from-workspaces"
    if legacy.parent.is_symlink() or legacy.is_symlink() or read_metadata(marker) != str(legacy):
        return False
    mounts = {m["Destination"]: m for m in value.get("Mounts", [])}
    if mounts.get("/data", {}).get("Source") != str(legacy / "data"):
        return False
    verify_existing(value, legacy / "data", legacy / "projects", host)
    return True


def migrate():
    """Explicitly copy legacy state, preserving owners, secrets and the original.

    This never repairs an unsafe credential owner. Bootstrap still checks the
    copied files. A partial copy remains for inspection and is never adopted.
    """
    if RUNTIME.is_symlink() or not RUNTIME.is_mount():
        raise RuntimeError("Persistent runtime volume is missing; rebuild the Dev Container")
    legacy = ROOT.parent / ".vibestack-codespaces" / ROOT.name
    state = RUNTIME / ROOT.name
    witness = legacy / "runtime-volume-id"
    for path in (legacy.parent, legacy, legacy / "data", legacy / "projects"):
        if path.is_symlink() or not path.is_dir():
            raise RuntimeError("Migration requires the original ordinary state directories")
    if os.path.lexists(state) or os.path.lexists(witness):
        raise RuntimeError("Migration destination or identity already exists; inspect it manually")
    marker = legacy / "data" / ".vibestack-state-v1"
    if marker.is_symlink() or not marker.is_dir():
        raise RuntimeError("Original directory is not marked as VibeStack state")
    old = inspect("container", CONTAINER)
    if old is not None:
        verify_existing(old, legacy / "data", legacy / "projects", public_host())
        if old["State"]["Running"]:
            run("docker", "stop", "--timeout", "20", CONTAINER)
    state.mkdir(mode=0o700)
    run("sudo", "-n", "--", "cp", "-a", "--", str(legacy / "data"),
        str(legacy / "projects"), str(state))
    value = secrets.token_hex(16)
    write_metadata(state / ".volume-id", value)
    write_metadata(state / ".migrated-from-workspaces", str(legacy))
    write_metadata(witness, value)
    print("State copied with original ownership; original retained. Inspect it, then run codespaces.py start.")


def run(*args, capture=False, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=capture,
                          cwd=ROOT, **kwargs)


def inspect(kind, name):
    result = subprocess.run(["docker", kind, "inspect", name], text=True,
                            capture_output=True, cwd=ROOT)
    if result.returncode:
        # A daemon failure must not be mistaken for an absent resource.
        run("docker", "info", capture=True)
        if "No such" not in result.stderr:
            raise RuntimeError(f"Cannot inspect {kind} {name}: {result.stderr.strip()}")
        return None
    return json.loads(result.stdout)[0]


def public_host():
    name = os.environ.get("CODESPACE_NAME", "")
    domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "")
    sys.path.insert(0, str(ROOT / "common"))
    from vibestack_hosts import configured_hosts
    host = f"{name}-8080.{domain}"
    if not name or not domain or configured_hosts(host) != frozenset([host]):
        raise RuntimeError("Codespaces forwarding hostname is missing or invalid")
    return host


def verify_existing(value, data, projects, host):
    mounts = {m["Destination"]: m for m in value.get("Mounts", [])}
    labels = value["Config"].get("Labels") or {}
    expected = {"/data": data, "/projects": projects}
    if labels.get("dev.vibestack.launch-contract") != "1" or any(
        mounts.get(target, {}).get("Type") != "bind"
        or mounts[target].get("Source") != str(source)
        for target, source in expected.items()
    ):
        raise RuntimeError("Existing container has unexpected mounts/labels; inspect it manually")
    source = mounts.get(f"/projects/{ROOT.name}")
    if source is not None and (source.get("Type") != "bind"
                              or source.get("Source") != str(ROOT)
                              or source.get("RW") is not True):
        raise RuntimeError("Existing source mount is unexpected; inspect it manually")
    # Upgrade pre-source-mount Codespaces through the launcher's rollback flow.
    env = value["Config"].get("Env", [])
    return (source is not None and f"VIBESTACK_ALLOWED_HOSTS={host}" in env
            and f"VIBESTACK_SOURCE_PROJECT={ROOT.name}" in env)


def start(data, projects, host):
    image = inspect("image", IMAGE)
    if image is None:
        run("docker", "build", "-t", IMAGE, str(ROOT))
        image = inspect("image", IMAGE)
    existing = inspect("container", CONTAINER)
    old_bind = existing is not None and migrated_existing(existing, data, projects, host)
    matches = existing is not None and not old_bind and verify_existing(existing, data, projects, host)
    if matches and existing["Image"] == image["Id"]:
        if not existing["State"]["Running"]:
            run("docker", "start", CONTAINER)
    else:
        # The normal launcher owns initial state marking and rollback on failure.
        env = {k: v for k, v in os.environ.items() if not k.startswith("VIBESTACK_")}
        env["VIBESTACK_PUBLIC_URL"] = f"https://{host}"
        run("bash", str(ROOT / "startup.sh"), "--no-build", "--image", IMAGE,
            "--name", CONTAINER, "--bind", "127.0.0.1", "--port", "8080",
            "--ssh-port", "0", "--vnc-port", "0", "--allowed-host", host,
            "--data", str(data), "--projects", str(projects), "--mount-source", env=env)
    for _ in range(90):
        value = inspect("container", CONTAINER)
        state = (value or {}).get("State", {})
        health = state.get("Health", {}).get("Status")
        if health == "healthy":
            request = urllib.request.Request("http://127.0.0.1:8080/healthz",
                                             headers={"Host": host})
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError("Forwarded-host health check failed")
            print(f"VibeStack ready: https://{host}/", flush=True)
            return
        if not state.get("Running") or health == "unhealthy":
            break
        time.sleep(2)
    raise RuntimeError(f"Desktop is not healthy; inspect: docker logs --tail 100 {CONTAINER}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "start", "rebuild", "migrate"])
    args = parser.parse_args()
    if os.environ.get("CODESPACES") != "true":
        print("Codespaces autostart skipped outside GitHub Codespaces.")
        return
    if ROOT.parent != Path("/workspaces"):
        raise RuntimeError("Expected a repository directly under /workspaces")
    if args.action == "migrate":
        wait_for_docker()
        migrate()
        return
    if args.action == "prepare":
        # Prebuilds prepare an image, never a workspace identity or credentials.
        # Runtime volumes need not be copied from a prebuild into a new Codespace.
        wait_for_docker()
        run("docker", "build", "-t", IMAGE, str(ROOT))
        return
    state = runtime_state()
    state.mkdir(parents=True, exist_ok=True)
    # Rebuild/start must never race over the same container or persistent data.
    with (state / "lifecycle.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        wait_for_docker()
        if args.action == "rebuild":
            run("docker", "build", "-t", IMAGE, str(ROOT))
        start(state / "data", state / "projects", public_host())


def wait_for_docker():
    for attempt in range(60):
        result = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return
        if attempt == 59:
            raise RuntimeError("Docker-in-Docker did not become ready within two minutes")
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError, UnicodeError) as error:
        print(f"VibeStack Codespaces: {error}", file=sys.stderr)
        sys.exit(1)
