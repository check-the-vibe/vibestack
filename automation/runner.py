"""Bounded asynchronous command runner for the automation service."""

from __future__ import annotations

import os
import queue
import re
import signal
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from jobs import Job, JobStore, TERMINAL_STATES


WORKER_COUNT = 4
QUEUE_CAPACITY = 32
DEFAULT_TIMEOUT_SECONDS = 30
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 300
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_PAGE_BYTES = 256 * 1024
KILL_GRACE_SECONDS = 2.0
PRLIMIT = "/usr/bin/prlimit"
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
TerminalEventHandler = Callable[[str, Mapping[str, object]], None]


class RunnerError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class CommandSpec:
    kind: str
    argv: tuple[str, ...]
    cwd: str
    env: Mapping[str, str]
    timeout_seconds: int
    request_id: str | None = None


class CommandRunner:
    def __init__(
        self,
        state_directory: str,
        *,
        worker_count: int = WORKER_COUNT,
        queue_capacity: int = QUEUE_CAPACITY,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
        terminal_event_handler: TerminalEventHandler | None = None,
    ):
        if worker_count < 1 or queue_capacity < 1:
            raise ValueError("runner capacity must be positive")
        self.store = JobStore(state_directory)
        self.max_output_bytes = max_output_bytes
        self.jobs = self.store.load_all()
        self._lock = threading.RLock()
        self._submission_lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._request_ids: dict[str, str] = {}
        self._terminal_event_handler = terminal_event_handler
        self._escalating: set[int] = set()
        self._queue: queue.Queue[tuple[Job, CommandSpec] | None] = queue.Queue(
            maxsize=queue_capacity
        )
        self._workers: list[threading.Thread] = []
        self._closed = False
        for index in range(worker_count):
            worker = threading.Thread(
                target=self._worker,
                name="automation-worker-%d" % index,
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)

    def set_terminal_event_handler(
        self, handler: TerminalEventHandler | None
    ) -> None:
        """Set the metadata-only sink used for future terminal job events."""

        with self._lock:
            self._terminal_event_handler = handler

    def submit(self, spec: CommandSpec) -> Job:
        if spec.kind not in ("command", "shell"):
            raise ValueError("invalid command kind")
        if spec.request_id is not None and not REQUEST_ID_RE.fullmatch(spec.request_id):
            raise ValueError("invalid request id")
        job = self.store.new(spec.kind)
        with self._submission_lock:
            with self._lock:
                if self._closed:
                    raise RunnerError("service_stopping", "The command runner is stopping.", 503)
                self.jobs[job.id] = job
                try:
                    self.store.save(job)
                except OSError as exc:
                    self.jobs.pop(job.id, None)
                    raise RunnerError(
                        "job_store_unavailable", "Job metadata could not be persisted.", 503
                    ) from exc
                if spec.request_id is not None:
                    self._request_ids[job.id] = spec.request_id
            try:
                self._queue.put_nowait((job, spec))
            except queue.Full:
                with self._lock:
                    self.jobs.pop(job.id, None)
                    self._request_ids.pop(job.id, None)
                    try:
                        self.store.metadata_path(job.id).unlink()
                    except FileNotFoundError:
                        pass
                raise RunnerError(
                    "job_queue_full", "The command queue is full; try again later.", 503
                ) from None
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise RunnerError("job_not_found", "The command job does not exist.", 404)
            return job

    def cancel(self, job_id: str) -> Job:
        process: subprocess.Popen[bytes] | None = None
        terminal_now = False
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise RunnerError("job_not_found", "The command job does not exist.", 404)
            if job.status in TERMINAL_STATES:
                return job
            first_request = not job.cancel_requested
            job.cancel_requested = True
            if job.status == "queued":
                job.status = "cancelled"
                job.error_code = "cancelled"
                job.finished_at = _now()
                self.store.save(job)
                self.store.prune(self.jobs)
                terminal_now = True
            elif first_request:
                process = self._processes.get(job.id)
        if terminal_now:
            self._emit_terminal_event(job)
        if process is not None:
            self._signal_process_group(process, signal.SIGTERM)
            self._schedule_forced_kill(process)
        return job

    def output_page(
        self, job_id: str, stream: str, cursor: int, limit: int
    ) -> dict[str, Any]:
        if stream not in ("stdout", "stderr"):
            raise RunnerError("invalid_stream", "stream must be stdout or stderr.", 400)
        if cursor < 0 or cursor > self.max_output_bytes:
            raise RunnerError("invalid_cursor", "cursor is outside the output range.", 400)
        if limit < 1 or limit > MAX_OUTPUT_PAGE_BYTES:
            raise RunnerError(
                "invalid_limit",
                "limit must be between 1 and %d." % MAX_OUTPUT_PAGE_BYTES,
                400,
            )
        job = self.get(job_id)
        path = self.store.output_path(job_id, stream)
        try:
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
        except FileNotFoundError:
            data = b""
            size = 0
        except OSError as exc:
            raise RunnerError("job_output_unavailable", "Job output is unavailable.", 503) from exc
        else:
            try:
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                    or info.st_size > self.max_output_bytes
                ):
                    raise RunnerError(
                        "job_output_unsafe", "Job output failed a safety check.", 503
                    )
                size = info.st_size
                if cursor > size:
                    raise RunnerError(
                        "invalid_cursor", "cursor is beyond the current output.", 400
                    )
                data = os.pread(fd, limit, cursor)
            finally:
                os.close(fd)
        if cursor > size:
            raise RunnerError("invalid_cursor", "cursor is beyond the current output.", 400)
        next_cursor = cursor + len(data)
        truncated = (
            job.stdout_truncated if stream == "stdout" else job.stderr_truncated
        )
        return {
            "data": data,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "eof": next_cursor >= size and job.status in TERMINAL_STATES,
            "truncated": truncated,
        }

    def shutdown(self, wait: bool = True) -> None:
        first_close = False
        processes: list[subprocess.Popen[bytes]] = []
        terminal_jobs: list[Job] = []
        with self._submission_lock:
            with self._lock:
                if not self._closed:
                    first_close = True
                    self._closed = True
                    for job in self.jobs.values():
                        if job.status not in TERMINAL_STATES:
                            job.cancel_requested = True
                    processes = list(self._processes.values())
            if first_close:
                while True:
                    try:
                        item = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        if item is not None:
                            job, _ = item
                            with self._lock:
                                if job.status not in TERMINAL_STATES:
                                    job.status = "cancelled"
                                    job.error_code = "service_stopping"
                                    job.finished_at = _now()
                                    self._save_best_effort(job)
                                    terminal_jobs.append(job)
                    finally:
                        self._queue.task_done()
                with self._lock:
                    try:
                        self.store.prune(self.jobs)
                    except OSError:
                        pass
        if first_close:
            for process in processes:
                self._signal_process_group(process, signal.SIGTERM)
                self._schedule_forced_kill(process)
            for job in terminal_jobs:
                self._emit_terminal_event(job)
        if wait:
            for worker in self._workers:
                worker.join(timeout=KILL_GRACE_SECONDS + 1)

    def _worker(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                with self._lock:
                    if self._closed:
                        return
                continue
            try:
                if item is None:
                    return
                job, spec = item
                try:
                    skip_execution = False
                    with self._lock:
                        if job.status == "cancelled" or job.cancel_requested or self._closed:
                            if job.status not in TERMINAL_STATES:
                                job.status = "cancelled"
                                job.error_code = "cancelled"
                                job.finished_at = _now()
                                self._save_best_effort(job)
                            skip_execution = True
                        else:
                            job.status = "running"
                            job.started_at = _now()
                            self.store.save(job)
                    if skip_execution:
                        self._emit_terminal_event(job)
                        continue
                    self._execute(job, spec)
                except Exception:
                    self._handle_worker_failure(job)
            finally:
                self._queue.task_done()

    def _handle_worker_failure(self, job: Job) -> None:
        with self._lock:
            process = self._processes.pop(job.id, None)
            job.status = "failed"
            job.error_code = "runner_internal_error"
            job.finished_at = _now()
            self._save_best_effort(job)
            try:
                self.store.prune(self.jobs)
            except OSError:
                pass
        self._emit_terminal_event(job)
        if process is not None:
            self._signal_process_group(process, signal.SIGTERM)
            self._schedule_forced_kill(process)

    def _save_best_effort(self, job: Job) -> None:
        try:
            self.store.save(job)
        except OSError:
            pass

    def _execute(self, job: Job, spec: CommandSpec) -> None:
        stdout_path = self.store.output_path(job.id, "stdout")
        stderr_path = self.store.output_path(job.id, "stderr")
        for path in (stdout_path, stderr_path):
            fd = os.open(
                path,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_CLOEXEC
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            os.close(fd)

        try:
            launch_argv = [
                PRLIMIT,
                "--core=0",
                "--cpu=%d" % (spec.timeout_seconds + 2),
                "--fsize=%d" % (64 * 1024 * 1024),
                "--nofile=256",
                "--as=%d" % (4 * 1024 * 1024 * 1024),
                "--",
                *spec.argv,
            ]
            process = subprocess.Popen(
                launch_argv,
                cwd=spec.cwd,
                env=dict(spec.env),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
        except (OSError, ValueError):
            with self._lock:
                job.status = "failed"
                job.error_code = "command_start_failed"
                job.finished_at = _now()
                self.store.save(job)
                self.store.prune(self.jobs)
            self._emit_terminal_event(job)
            return

        with self._lock:
            self._processes[job.id] = process
            cancelled_before_registration = job.cancel_requested
        if cancelled_before_registration:
            self._signal_process_group(process, signal.SIGTERM)
            self._schedule_forced_kill(process)

        assert process.stdout is not None and process.stderr is not None
        stream_results: dict[str, tuple[int, bool, bool]] = {}
        output_threads = [
            threading.Thread(
                target=self._pump,
                args=(process.stdout, stdout_path, stream_results, "stdout"),
                daemon=True,
            ),
            threading.Thread(
                target=self._pump,
                args=(process.stderr, stderr_path, stream_results, "stderr"),
                daemon=True,
            ),
        ]
        for thread in output_threads:
            thread.start()

        timed_out = False
        try:
            process.wait(timeout=spec.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._signal_process_group(process, signal.SIGTERM)
            try:
                process.wait(timeout=KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                self._signal_process_group(process, signal.SIGKILL)
                process.wait()
        finally:
            # A command leader may exit after leaving ordinary background
            # descendants in its original process group. Jobs do not publish
            # a terminal state until that whole group has been closed.
            self._signal_process_group(process, signal.SIGTERM)
            if not self._wait_process_group(process, KILL_GRACE_SECONDS):
                self._signal_process_group(process, signal.SIGKILL)
                self._wait_process_group(process, 1.0)
            for thread in output_threads:
                thread.join(timeout=KILL_GRACE_SECONDS + 1)
            with self._lock:
                self._processes.pop(job.id, None)

        stdout_bytes, stdout_truncated, stdout_error = stream_results.get(
            "stdout", (0, False, True)
        )
        stderr_bytes, stderr_truncated, stderr_error = stream_results.get(
            "stderr", (0, False, True)
        )
        output_error = stdout_error or stderr_error or any(
            thread.is_alive() for thread in output_threads
        )
        with self._lock:
            job.stdout_bytes = stdout_bytes
            job.stderr_bytes = stderr_bytes
            job.stdout_truncated = stdout_truncated
            job.stderr_truncated = stderr_truncated
            job.exit_code = process.returncode
            if job.cancel_requested:
                job.status = "cancelled"
                job.error_code = "cancelled"
            elif timed_out:
                job.status = "timed_out"
                job.error_code = "timeout"
            elif output_error:
                job.status = "failed"
                job.error_code = "job_output_failed"
            elif process.returncode == 0:
                job.status = "succeeded"
            else:
                job.status = "failed"
                job.error_code = "nonzero_exit"
            job.finished_at = _now()
            self.store.save(job)
            self.store.prune(self.jobs)
        self._emit_terminal_event(job)

    def _emit_terminal_event(self, job: Job) -> None:
        """Attempt one redacted terminal event without affecting job state."""

        with self._lock:
            if job.status not in TERMINAL_STATES:
                return
            # Popping the request ID is the exactly-once guard. It also bounds
            # retained correlation state independently of job-store pruning.
            request_id = self._request_ids.pop(job.id, None)
            handler = self._terminal_event_handler
            if request_id is None or handler is None:
                return
            details: Mapping[str, object] = {
                "job_id": job.id,
                "kind": job.kind,
                "status": job.status,
                "exit_code": job.exit_code,
                "error_code": job.error_code,
                "stdout_bytes": job.stdout_bytes,
                "stderr_bytes": job.stderr_bytes,
                "stdout_truncated": job.stdout_truncated,
                "stderr_truncated": job.stderr_truncated,
            }
        try:
            handler(request_id, details)
        except Exception:
            # Audit logging is intentionally best-effort and must never turn a
            # completed job into a failed worker or API operation.
            pass

    def _pump(
        self,
        source: Any,
        output_path: os.PathLike[str] | str,
        results: dict[str, tuple[int, bool, bool]],
        stream: str,
    ) -> None:
        written = 0
        truncated = False
        output_error = False
        fd = -1
        try:
            try:
                fd = os.open(
                    output_path,
                    os.O_WRONLY
                    | os.O_APPEND
                    | os.O_CLOEXEC
                    | getattr(os, "O_NOFOLLOW", 0),
                )
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                ):
                    raise OSError("unsafe job output file")
            except OSError:
                output_error = True
                if fd >= 0:
                    os.close(fd)
                    fd = -1
            # BufferedReader.read(n) may wait for all n bytes and hide small
            # progress writes until the process exits. read1() performs one
            # underlying pipe read, making running-job output observable.
            read_chunk = getattr(source, "read1", source.read)
            while True:
                chunk = read_chunk(64 * 1024)
                if not chunk:
                    break
                remaining = self.max_output_bytes - written
                if remaining > 0 and fd >= 0:
                    selected = chunk[:remaining]
                    view = memoryview(selected)
                    offset = 0
                    try:
                        while offset < len(view):
                            offset += os.write(fd, view[offset:])
                        written += len(selected)
                    except OSError:
                        output_error = True
                        os.close(fd)
                        fd = -1
                if len(chunk) > max(remaining, 0):
                    truncated = True
        except OSError:
            output_error = True
        finally:
            source.close()
            if fd >= 0:
                os.close(fd)
            results[stream] = (written, truncated, output_error)

    @staticmethod
    def _signal_process_group(
        process: subprocess.Popen[bytes], signal_number: signal.Signals
    ) -> None:
        try:
            # start_new_session makes the child PID its process-group ID.
            os.killpg(process.pid, signal_number)
        except ProcessLookupError:
            pass

    @staticmethod
    def _process_group_exists(process: subprocess.Popen[bytes]) -> bool:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _wait_process_group(
        self, process: subprocess.Popen[bytes], timeout: float
    ) -> bool:
        deadline = time.monotonic() + timeout
        while self._process_group_exists(process):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)
        return True

    def _schedule_forced_kill(self, process: subprocess.Popen[bytes]) -> None:
        process_key = id(process)
        with self._lock:
            if process_key in self._escalating:
                return
            self._escalating.add(process_key)

        def escalate() -> None:
            try:
                deadline = time.monotonic() + KILL_GRACE_SECONDS
                while self._process_group_exists(process):
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.02)
                if self._process_group_exists(process):
                    self._signal_process_group(process, signal.SIGKILL)
                    self._wait_process_group(process, 1.0)
                try:
                    process.wait(timeout=0)
                except subprocess.TimeoutExpired:
                    pass
            except OSError:
                self._signal_process_group(process, signal.SIGKILL)
            finally:
                with self._lock:
                    self._escalating.discard(process_key)

        threading.Thread(
            target=escalate,
            name="automation-cancel-escalation",
            daemon=True,
        ).start()


def _now() -> str:
    from jobs import utc_now

    return utc_now()
