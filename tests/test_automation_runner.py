from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation"))
import automationlib as lib  # noqa: E402
from jobs import Job  # noqa: E402
from jobs import JobStore  # noqa: E402
import runner  # noqa: E402


class CommandRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.desktop = root / "Desktop"
        self.desktop.mkdir()
        self.state = root / "jobs"
        self.runner = runner.CommandRunner(
            str(self.state), worker_count=1, queue_capacity=2, max_output_bytes=64
        )
        self.environment = {
            "HOME": str(root),
            "PATH": "/usr/bin:/bin",
            "DISPLAY": ":0",
        }

    def tearDown(self):
        self.runner.shutdown()
        self.temporary.cleanup()

    def submit(self, argv, timeout=5, request_id=None):
        return self.runner.submit(
            runner.CommandSpec(
                kind="command",
                argv=tuple(argv),
                cwd=str(self.desktop),
                env=self.environment,
                timeout_seconds=timeout,
                request_id=request_id,
            )
        )

    def wait_terminal(self, job, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if job.status in runner.TERMINAL_STATES:
                return job
            time.sleep(0.02)
        self.fail("job did not reach a terminal state")

    def test_job_runs_and_pages_bounded_byte_output(self):
        job = self.wait_terminal(self.submit(["/usr/bin/printf", "hello"]), timeout=5)
        self.assertEqual("succeeded", job.status, job.public())
        self.assertEqual(0, job.exit_code)
        page = self.runner.output_page(job.id, "stdout", 1, 3)
        self.assertEqual(b"ell", page["data"])
        self.assertEqual(4, page["next_cursor"])
        self.assertFalse(page["truncated"])

    def test_output_is_truncated_on_disk_without_blocking_child(self):
        job = self.wait_terminal(
            self.submit(["/usr/bin/head", "-c", "1024", "/dev/zero"]),
            timeout=5,
        )
        self.assertEqual("succeeded", job.status, job.public())
        self.assertEqual(64, job.stdout_bytes)
        self.assertTrue(job.stdout_truncated)
        self.assertEqual(64, self.runner.store.output_path(job.id, "stdout").stat().st_size)

    def test_small_output_is_visible_while_job_is_still_running(self):
        source = 'import time; print("ready", flush=True); time.sleep(2)'
        job = self.submit(["/usr/bin/python3", "-c", source], timeout=5)
        deadline = time.monotonic() + 1.5
        data = b""
        while time.monotonic() < deadline:
            data = self.runner.output_page(job.id, "stdout", 0, 64)["data"]
            if data:
                break
            time.sleep(0.02)
        self.assertEqual(b"ready\n", data)
        self.assertEqual("running", job.status)

    def test_normal_leader_exit_cleans_up_background_descendants(self):
        self.runner.max_output_bytes = 4096
        source = (
            'import subprocess; child=subprocess.Popen(["/bin/sleep","30"]); '
            'print(child.pid, flush=True)'
        )
        job = self.wait_terminal(
            self.submit(["/usr/bin/python3", "-c", source]), timeout=6
        )
        diagnostic = self.runner.output_page(job.id, "stderr", 0, 4096)["data"].decode(
            "utf-8", "replace"
        )
        self.assertEqual("succeeded", job.status, "%r stderr=%s" % (job.public(), diagnostic))
        page = self.runner.output_page(job.id, "stdout", 0, 64)
        child_pid = int(page["data"].strip())
        deadline = time.monotonic() + 2
        while Path("/proc/%d" % child_pid).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(Path("/proc/%d" % child_pid).exists())

    def test_timeout_and_cancel_terminate_process_groups(self):
        timed_out = self.wait_terminal(self.submit(["/bin/sleep", "5"], timeout=1), timeout=4)
        self.assertEqual("timed_out", timed_out.status)

        cancelled = self.submit(["/bin/sleep", "5"])
        deadline = time.monotonic() + 2
        while cancelled.status != "running" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.runner.cancel(cancelled.id)
        self.wait_terminal(cancelled, timeout=3)
        self.assertEqual("cancelled", cancelled.status)

    def test_cancel_during_spawn_race_still_escalates(self):
        real_popen = runner.subprocess.Popen
        entered = runner.threading.Event()
        release = runner.threading.Event()

        def delayed_popen(*args, **kwargs):
            entered.set()
            release.wait(timeout=2)
            return real_popen(*args, **kwargs)

        with mock.patch.object(runner.subprocess, "Popen", delayed_popen):
            job = self.submit(
                [
                    "/usr/bin/python3",
                    "-c",
                    "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
                ],
                timeout=30,
            )
            self.assertTrue(entered.wait(timeout=2))
            self.assertEqual("running", job.status)
            self.runner.cancel(job.id)
            release.set()
            self.wait_terminal(job, timeout=5)
        self.assertEqual("cancelled", job.status)

    def test_sensitive_command_is_not_persisted_in_metadata(self):
        secret = "never-store-this-command-source"
        job = self.wait_terminal(self.submit(["/usr/bin/printf", secret]), timeout=5)
        metadata = self.runner.store.metadata_path(job.id).read_text(encoding="utf-8")
        self.assertNotIn(secret, metadata)
        stored = json.loads(metadata)
        self.assertNotIn("argv", stored)
        self.assertNotIn("env", stored)

    def test_terminal_events_are_exactly_once_redacted_and_best_effort(self):
        events = []
        self.runner.set_terminal_event_handler(
            lambda request_id, details: events.append((request_id, dict(details)))
        )
        secret = "terminal-event-must-not-contain-this"
        succeeded = self.wait_terminal(
            self.submit(
                ["/usr/bin/printf", secret],
                request_id="request-success",
            )
        )
        deadline = time.monotonic() + 2
        while len(events) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(1, len(events))
        request_id, details = events[0]
        self.assertEqual("request-success", request_id)
        self.assertEqual(
            {
                "job_id": succeeded.id,
                "kind": "command",
                "status": "succeeded",
                "exit_code": 0,
                "error_code": None,
                "stdout_bytes": len(secret),
                "stderr_bytes": 0,
                "stdout_truncated": False,
                "stderr_truncated": False,
            },
            details,
        )
        self.assertNotIn(secret, json.dumps(events))
        self.assertNotIn("argv", details)
        self.assertNotIn("env", details)

        cancelled = self.submit(
            ["/bin/sleep", "30"], request_id="request-cancelled"
        )
        deadline = time.monotonic() + 2
        while cancelled.status != "running" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual("running", cancelled.status)
        self.runner.cancel(cancelled.id)
        self.runner.cancel(cancelled.id)
        self.wait_terminal(cancelled, timeout=4)
        self.runner.cancel(cancelled.id)
        deadline = time.monotonic() + 2
        while len(events) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        cancelled_events = [
            event for event in events if event[1]["job_id"] == cancelled.id
        ]
        self.assertEqual(1, len(cancelled_events))
        self.assertEqual("request-cancelled", cancelled_events[0][0])
        self.assertEqual("cancelled", cancelled_events[0][1]["status"])
        self.assertEqual("cancelled", cancelled_events[0][1]["error_code"])

        def broken_logger(_request_id, _details):
            raise OSError("simulated audit failure")

        self.runner.set_terminal_event_handler(broken_logger)
        still_succeeds = self.wait_terminal(
            self.submit(["/usr/bin/true"], request_id="request-log-failure")
        )
        self.assertEqual("succeeded", still_succeeds.status)

    def test_worker_survives_a_metadata_io_failure(self):
        original_save = self.runner.store.save
        calls = 0

        def flaky_save(job):
            nonlocal calls
            calls += 1
            if calls == 2:  # first worker transition after successful submission
                raise OSError("simulated job-store failure")
            return original_save(job)

        self.runner.store.save = flaky_save
        failed = self.wait_terminal(self.submit(["/usr/bin/printf", "first"]), timeout=3)
        self.assertEqual("failed", failed.status)
        self.assertEqual("runner_internal_error", failed.error_code)
        self.runner.store.save = original_save
        succeeded = self.wait_terminal(self.submit(["/usr/bin/printf", "second"]), timeout=3)
        self.assertEqual("succeeded", succeeded.status)

    def test_shutdown_does_not_block_on_a_full_queue(self):
        other = runner.CommandRunner(
            str(Path(self.temporary.name) / "shutdown-jobs"),
            worker_count=1,
            queue_capacity=1,
        )
        real_popen = runner.subprocess.Popen
        entered = runner.threading.Event()
        release = runner.threading.Event()

        def delayed_popen(*args, **kwargs):
            entered.set()
            release.wait(timeout=2)
            return real_popen(*args, **kwargs)

        try:
            with mock.patch.object(runner.subprocess, "Popen", delayed_popen):
                spec = runner.CommandSpec(
                    kind="command",
                    argv=("/bin/sleep", "10"),
                    cwd=str(self.desktop),
                    env=self.environment,
                    timeout_seconds=10,
                )
                other.submit(spec)
                self.assertTrue(entered.wait(timeout=2))
                queued = other.submit(spec)
                started = time.monotonic()
                other.shutdown(wait=False)
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertEqual("cancelled", queued.status)
                release.set()
        finally:
            release.set()
            other.shutdown(wait=True)

    def test_queued_cancellation_prunes_finished_metadata(self):
        other = runner.CommandRunner(
            str(Path(self.temporary.name) / "prune-jobs"),
            worker_count=1,
            queue_capacity=4,
        )
        other.store.max_jobs = 2
        spec = runner.CommandSpec(
            kind="command",
            argv=("/bin/sleep", "10"),
            cwd=str(self.desktop),
            env=self.environment,
            timeout_seconds=10,
        )
        try:
            blocker = other.submit(spec)
            deadline = time.monotonic() + 2
            while blocker.status != "running" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual("running", blocker.status)
            for _ in range(3):
                queued = other.submit(spec)
                other.cancel(queued.id)
                self.assertEqual("cancelled", queued.status)
            self.assertLessEqual(len(other.jobs), 2)
            self.assertLessEqual(len(list(other.store.directory.glob("*.json"))), 2)
        finally:
            other.cancel(blocker.id)
            other.shutdown()

    def test_restart_prunes_old_and_orphaned_job_files(self):
        directory = Path(self.temporary.name) / "restart-retention"
        store = JobStore(str(directory), max_jobs=2)
        created = []
        for index in range(4):
            job = store.new("command")
            job.status = "succeeded"
            job.finished_at = "2026-01-01T00:00:0%dZ" % index
            store.save(job)
            store.output_path(job.id, "stdout").write_bytes(b"output")
            created.append(job.id)
            time.sleep(0.002)
        orphan = "f" * 32
        store.output_path(orphan, "stderr").write_bytes(b"orphan")

        recovered = store.load_all()
        self.assertEqual(set(created[-2:]), set(recovered))
        self.assertEqual(2, len(list(directory.glob("*.json"))))
        self.assertFalse(store.output_path(orphan, "stderr").exists())
        self.assertFalse(store.output_path(created[0], "stdout").exists())

    def test_backend_shell_is_explicit_bash_lc_and_protects_desktop_env(self):
        captured = []

        class CapturingRunner:
            def submit(self, spec):
                captured.append(spec)
                return Job(id="0" * 32, kind=spec.kind)

            def shutdown(self, wait=False):
                pass

        backend = lib.AutomationBackend(
            desktop_root=str(self.desktop),
            job_directory=str(self.state),
            runner=CapturingRunner(),
        )
        payload = backend.submit_command(
            {"command": "printf ok", "env": {"TASK_VALUE": "yes"}}, shell=True
        )
        self.assertEqual("shell", payload["job"]["kind"])
        self.assertEqual(("/bin/bash", "-lc", "printf ok"), captured[0].argv)
        self.assertEqual(":0", captured[0].env["DISPLAY"])
        self.assertEqual("yes", captured[0].env["TASK_VALUE"])
        with self.assertRaises(lib.AutomationError):
            backend.submit_command(
                {"command": "true", "env": {"DISPLAY": ":99"}}, shell=True
            )


if __name__ == "__main__":
    unittest.main()
