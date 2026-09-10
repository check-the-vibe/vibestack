"""Persistent, content-free metadata for bounded automation command jobs."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
JOB_FILE_RE = re.compile(r"^([0-9a-f]{32})\.(json|stdout|stderr)$")
JOB_TEMP_RE = re.compile(r"^\.([0-9a-f]{32})\.[A-Za-z0-9_.-]+\.tmp$")
TERMINAL_STATES = frozenset(
    {"succeeded", "failed", "timed_out", "cancelled", "interrupted"}
)
ALL_STATES = TERMINAL_STATES | {"queued", "running"}


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error_code: str | None = None
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    cancel_requested: bool = False

    def public(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "output": {
                "stdout_bytes": self.stdout_bytes,
                "stderr_bytes": self.stderr_bytes,
                "stdout_truncated": self.stdout_truncated,
                "stderr_truncated": self.stderr_truncated,
            },
        }
        if self.error_code is not None:
            payload["error_code"] = self.error_code
        return payload

    def stored(self) -> dict[str, Any]:
        # Commands, shell source, cwd, environment and stdin are deliberately
        # absent. A persisted job record is safe to expose as metadata.
        return self.public()

    @classmethod
    def from_stored(cls, value: object) -> "Job":
        if not isinstance(value, dict):
            raise ValueError("job metadata is not an object")
        job_id = value.get("id")
        kind = value.get("kind")
        status = value.get("status")
        created_at = value.get("created_at")
        if (
            not isinstance(job_id, str)
            or not JOB_ID_RE.fullmatch(job_id)
            or kind not in ("command", "shell")
            or status not in ALL_STATES
            or not isinstance(created_at, str)
        ):
            raise ValueError("invalid job metadata")
        output = value.get("output")
        if not isinstance(output, dict):
            output = {}
        job = cls(
            id=job_id,
            kind=kind,
            status=status,
            created_at=created_at,
            started_at=value.get("started_at")
            if isinstance(value.get("started_at"), str)
            else None,
            finished_at=value.get("finished_at")
            if isinstance(value.get("finished_at"), str)
            else None,
            exit_code=value.get("exit_code")
            if isinstance(value.get("exit_code"), int)
            else None,
            error_code=value.get("error_code")
            if isinstance(value.get("error_code"), str)
            else None,
            stdout_bytes=_stored_count(output.get("stdout_bytes")),
            stderr_bytes=_stored_count(output.get("stderr_bytes")),
            stdout_truncated=output.get("stdout_truncated") is True,
            stderr_truncated=output.get("stderr_truncated") is True,
        )
        # A process cannot survive the service that owned and tracked its
        # process group. Make recovery explicit rather than claiming it runs.
        if job.status in ("queued", "running"):
            job.status = "interrupted"
            job.error_code = "service_restarted"
            job.finished_at = utc_now()
        return job


def _stored_count(value: object) -> int:
    return value if isinstance(value, int) and 0 <= value <= 4 * 1024 * 1024 else 0


class JobStore:
    """Small atomic metadata store with fixed, generated file names."""

    def __init__(self, directory: str, max_jobs: int = 256):
        self.directory = Path(directory)
        self.max_jobs = max_jobs
        self._lock = threading.RLock()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.directory, flags)
            try:
                info = os.fstat(fd)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                    raise OSError("unsafe job directory")
                os.fchmod(fd, 0o700)
            finally:
                os.close(fd)
        except OSError as exc:
            raise OSError("job directory failed a safety check") from exc

    def new(self, kind: str) -> Job:
        return Job(id=uuid.uuid4().hex, kind=kind)

    def metadata_path(self, job_id: str) -> Path:
        require_job_id(job_id)
        return self.directory / (job_id + ".json")

    def output_path(self, job_id: str, stream: str) -> Path:
        require_job_id(job_id)
        if stream not in ("stdout", "stderr"):
            raise ValueError("invalid output stream")
        return self.directory / (job_id + "." + stream)

    def save(self, job: Job) -> None:
        body = json.dumps(
            job.stored(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        with self._lock:
            fd, temporary = tempfile.mkstemp(
                prefix="." + job.id + ".", suffix=".tmp", dir=self.directory
            )
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb", closefd=True) as output:
                    output.write(body)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.metadata_path(job.id))
            except BaseException:
                try:
                    os.close(fd)
                except OSError:
                    pass
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise

    def load_all(self) -> dict[str, Job]:
        jobs: dict[str, Job] = {}
        with self._lock:
            safe_files: dict[str, tuple[Path, os.stat_result]] = {}
            try:
                entries = list(os.scandir(self.directory))
            except OSError:
                entries = []
            for entry in entries:
                if not (JOB_FILE_RE.fullmatch(entry.name) or JOB_TEMP_RE.fullmatch(entry.name)):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if (
                    stat_is_safe_regular(info)
                    and info.st_uid == os.getuid()
                    and info.st_nlink == 1
                ):
                    safe_files[entry.name] = (Path(entry.path), info)

            metadata = sorted(
                (
                    value
                    for name, value in safe_files.items()
                    if name.endswith(".json")
                ),
                key=lambda value: value[1].st_mtime_ns,
                reverse=True,
            )
            recovered: list[Job] = []
            for path, info in metadata:
                if len(recovered) >= self.max_jobs:
                    break
                try:
                    if info.st_size > 16 * 1024:
                        continue
                    parsed = json.loads(self._read_metadata(path))
                    job = Job.from_stored(parsed)
                except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
                    continue
                jobs[job.id] = job
                recovered.append(job)
                if parsed.get("status") in ("queued", "running"):
                    self.save(job)
            retained_ids = set(jobs)
            for name, (path, _) in safe_files.items():
                match = JOB_FILE_RE.fullmatch(name)
                if JOB_TEMP_RE.fullmatch(name) or (match and match.group(1) not in retained_ids):
                    try:
                        path.unlink()
                    except OSError:
                        pass
        return jobs

    @staticmethod
    def _read_metadata(path: Path) -> str:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            before = os.fstat(fd)
            if (
                not stat_is_safe_regular(before)
                or before.st_uid != os.getuid()
                or before.st_nlink != 1
                or before.st_size > 16 * 1024
            ):
                raise ValueError("unsafe job metadata")
            raw = os.read(fd, 16 * 1024 + 1)
            after = os.fstat(fd)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("job metadata changed")
            return raw.decode("utf-8")
        finally:
            os.close(fd)

    def prune(self, jobs: dict[str, Job]) -> None:
        """Retain active jobs and the newest bounded set of finished jobs."""

        with self._lock:
            finished = sorted(
                (job for job in jobs.values() if job.status in TERMINAL_STATES),
                key=lambda job: job.finished_at or job.created_at,
                reverse=True,
            )
            keep_finished = max(0, self.max_jobs - (len(jobs) - len(finished)))
            for job in finished[keep_finished:]:
                jobs.pop(job.id, None)
                for path in (
                    self.metadata_path(job.id),
                    self.output_path(job.id, "stdout"),
                    self.output_path(job.id, "stderr"),
                ):
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass


def require_job_id(job_id: str) -> str:
    if not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("invalid job id")
    return job_id


def stat_is_safe_regular(info: os.stat_result) -> bool:
    return stat.S_ISREG(info.st_mode)
