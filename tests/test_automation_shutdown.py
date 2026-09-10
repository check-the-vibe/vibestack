"""Subprocess regression for automation service signal cleanup."""

from __future__ import annotations

import base64
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "automation" / "server.py"
TOKEN = "s" * 43
PREFIX = "/api/v1/automation"


def available_loopback_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


class AutomationSignalShutdownTests(unittest.TestCase):
    def test_sigterm_closes_running_command_process_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            desktop = root / "Desktop"
            desktop.mkdir()
            token_path = root / "automation.token"
            token_path.write_text(TOKEN + "\n", encoding="ascii")
            token_path.chmod(0o600)
            port = available_loopback_port()
            environment = os.environ.copy()
            environment.update(
                AUTOMATION_PORT=str(port),
                AUTOMATION_TOKEN_FILE=str(token_path),
                AUTOMATION_DESKTOP_ROOT=str(desktop),
                AUTOMATION_JOB_DIR=str(root / "jobs"),
                AUTOMATION_AUDIT_LOG=str(root / "audit.jsonl"),
                AUTOMATION_SESSION_ENV_FILE=str(root / "missing-session.env"),
                AUTOMATION_XDG_RUNTIME_DIR=str(root / "runtime"),
                PYTHONDONTWRITEBYTECODE="1",
            )
            service = subprocess.Popen(
                [sys.executable, str(SERVER)],
                cwd=str(ROOT),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            child_pid = None
            try:
                deadline = time.monotonic() + 5
                while True:
                    if service.poll() is not None:
                        stdout, stderr = service.communicate(timeout=1)
                        self.fail(
                            "automation service exited during startup: %s %s"
                            % (stdout, stderr)
                        )
                    try:
                        status, _ = self.request(port, "GET", PREFIX)
                        if status == 200:
                            break
                    except OSError:
                        pass
                    if time.monotonic() >= deadline:
                        self.fail("automation service did not become ready")
                    time.sleep(0.03)

                source = "import os,time; print(os.getpid(),flush=True); time.sleep(60)"
                status, payload = self.request(
                    port,
                    "POST",
                    PREFIX + "/commands",
                    {"argv": [sys.executable, "-c", source], "timeout_seconds": 60},
                )
                self.assertEqual(202, status)
                job_id = payload["job"]["id"]

                deadline = time.monotonic() + 5
                last_job = payload["job"]
                while time.monotonic() < deadline:
                    status, metadata = self.request(
                        port, "GET", PREFIX + "/jobs/%s" % job_id
                    )
                    self.assertEqual(200, status)
                    last_job = metadata["job"]
                    status, output = self.request(
                        port,
                        "GET",
                        PREFIX
                        + "/jobs/%s/output?stream=stdout&cursor=0&limit=128"
                        % job_id,
                    )
                    self.assertEqual(200, status)
                    raw = base64.b64decode(output["data"])
                    if raw.strip():
                        child_pid = int(raw.strip())
                        break
                    time.sleep(0.03)
                self.assertIsNotNone(
                    child_pid, "command did not publish its PID: %r" % last_job
                )
                self.assertTrue(Path("/proc/%d" % child_pid).exists())

                service.send_signal(signal.SIGTERM)
                self.assertEqual(0, service.wait(timeout=8))
                deadline = time.monotonic() + 3
                while Path("/proc/%d" % child_pid).exists() and time.monotonic() < deadline:
                    time.sleep(0.03)
                self.assertFalse(
                    Path("/proc/%d" % child_pid).exists(),
                    "running command survived automation service SIGTERM",
                )
            finally:
                if service.poll() is None:
                    service.kill()
                    service.wait(timeout=3)
                service.communicate(timeout=1)
                if child_pid is not None and Path("/proc/%d" % child_pid).exists():
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    @staticmethod
    def request(port, method, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        headers = {"Authorization": "Bearer " + TOKEN}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
