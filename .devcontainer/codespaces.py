#!/usr/bin/env python3
"""Build and resume the private VibeStack desktop inside a Codespace."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "vibestack:codespaces"
CONTAINER = "vibestack-codespaces"


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
    return f"VIBESTACK_ALLOWED_HOSTS={host}" in value["Config"].get("Env", [])


def start(data, projects, host):
    image = inspect("image", IMAGE)
    if image is None:
        run("docker", "build", "-t", IMAGE, str(ROOT))
        image = inspect("image", IMAGE)
    existing = inspect("container", CONTAINER)
    matches = existing is not None and verify_existing(existing, data, projects, host)
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
            "--data", str(data), "--projects", str(projects), env=env)
    for _ in range(90):
        value = inspect("container", CONTAINER)
        state = (value or {}).get("State", {})
        health = state.get("Health", {}).get("Status")
        if health == "healthy":
            request = urllib.request.Request("http://127.0.0.1:8080/api/v1/status",
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
    parser.add_argument("action", choices=["prepare", "start", "rebuild"])
    args = parser.parse_args()
    if os.environ.get("CODESPACES") != "true":
        print("Codespaces autostart skipped outside GitHub Codespaces.")
        return
    if ROOT.parent != Path("/workspaces"):
        raise RuntimeError("Expected a repository directly under /workspaces")
    state = ROOT.parent / ".vibestack-codespaces" / ROOT.name
    state.mkdir(parents=True, exist_ok=True)
    # Rebuild/start must never race over the same container or persistent data.
    with (state / "lifecycle.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for attempt in range(60):
            result = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                break
            if attempt == 59:
                raise RuntimeError("Docker-in-Docker did not become ready within two minutes")
            time.sleep(2)
        if args.action in {"prepare", "rebuild"}:
            run("docker", "build", "-t", IMAGE, str(ROOT))
        if args.action != "prepare":
            start(state / "data", state / "projects", public_host())


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f"VibeStack Codespaces: {error}", file=sys.stderr)
        sys.exit(1)
