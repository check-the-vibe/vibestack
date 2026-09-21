#!/usr/bin/env python3
"""Verify MCP editing the real Codespace checkout in an isolated desktop.

Run only after the supplied candidate passes full disposable acceptance. This
creates temporary state and a short-lived scoped credential in its own container;
it never reads GitHub tokens or credentials from the running VibeStack desktop.
"""

import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.environ.get("CODESPACES") != "true" or len(sys.argv) != 2:
        raise RuntimeError("Run inside Codespaces with one already-accepted image argument")
    if ROOT.parent != Path("/workspaces") or not (ROOT / ".git").exists():
        raise RuntimeError("Expected a Codespaces Git checkout under /workspaces")
    image = sys.argv[1]
    inspected = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                               check=True, capture_output=True, text=True).stdout.strip()
    if not inspected.startswith("sha256:"):
        raise RuntimeError("Candidate image was not resolved")
    # Pin all container launches and cleanup to the inspected candidate digest.
    image = inspected
    port = os.environ.get("VIBESTACK_SOURCE_PROBE_PORT", "18083")
    if not port.isascii() or not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise RuntimeError("Invalid isolated probe port")
    container = "vibestack-source-probe-" + secrets.token_hex(6)
    directory = Path(tempfile.mkdtemp(prefix="vibestack-codespaces-mcp-"))
    data, projects = directory / "data", directory / "projects"
    projects.mkdir(mode=0o755)
    log_path = directory / "probe.log"
    stage = "build client"
    try:
        with log_path.open("wb") as log:
            def run(*args, env=None):
                subprocess.run(args, check=True, cwd=ROOT, env=env,
                               stdout=log, stderr=subprocess.STDOUT, timeout=300)
            binary = directory / "vibestack"
            run("go", "build", "-buildvcs=false", "-o", str(binary), "./cmd/vibestack")
            stage = "start isolated desktop with source bind"
            run("bash", "startup.sh", "--no-build", "--image", image,
                "--name", container, "--port", port, "--ssh-port", "0", "--vnc-port", "0",
                "--data", str(data), "--projects", str(projects), "--mount-source")
            stage = "create disposable scoped credential"
            run("docker", "exec", "-u", "vibe", container, "vibestack-service", "credential", "create",
                "--label", "disposable-source-check", "--expires-in", "10m",
                "--capabilities", "workspaceStatus,submitArgvCommand,getWorkspaceJob,getWorkspaceJobOutput,readProjectFile,writeProjectFile,captureWorkspaceScreenshot",
                "--output", "/data/vibestack/source-check.token")
            token_file = directory / "source-check.token"
            run("docker", "cp", container + ":/data/vibestack/source-check.token", str(token_file))
            token_file.chmod(0o600)
            stage = "stdio and shared checkout"
            env = {**os.environ,
                   "VIBESTACK_ALLOW_MUTATING_MCP_TESTS": "1",
                   "VIBESTACK_MCP_BASE_URL": "http://127.0.0.1:" + port,
                   "VIBESTACK_MCP_CREDENTIAL_FILE": str(token_file),
                   "VIBESTACK_MCP_CLI": str(binary),
                   "VIBESTACK_MCP_PROBE_PROJECT": ROOT.name,
                   "VIBESTACK_MCP_SOURCE_ROOT": str(ROOT)}
            run("node", "tests/mcp-stdio-check.mjs", env=env)
        print("PASS Codespaces-local stdio: status, argv/output, conditional file update visible in shared Git checkout, stale-write denial and screenshot; probe file removed")
        print("Candidate:", image)
    except (OSError, subprocess.SubprocessError) as exc:
        # Do not copy command/provider diagnostics or credential content to chat.
        raise RuntimeError("Codespaces MCP check failed at " + stage + "; protected log: " + str(log_path)) from None
    finally:
        subprocess.run(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, timeout=60)
        # Only the two state directories just created above are root-owned.
        # The live checkout was a nested container bind, not a host child here.
        cleaned = subprocess.run(["docker", "run", "--rm", "--entrypoint", "/bin/rm",
                                  "--mount", "type=bind,source=" + str(directory) + ",target=/cleanup",
                                  image, "-rf", "--", "/cleanup/data", "/cleanup/projects"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 check=False, timeout=60)
        if cleaned.returncode == 0:
            # Retain a private failure log; successful fixtures are removed fully.
            if sys.exc_info()[0] is None:
                shutil.rmtree(directory)
            else:
                for filename in ("source-check.token", "vibestack"):
                    (directory / filename).unlink(missing_ok=True)
        else:
            raise RuntimeError("Temporary source-check cleanup failed; inspect " + str(directory))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
