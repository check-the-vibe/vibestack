from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import ISO_FORMAT, SessionMetadata, SessionStatus


class SessionStorage:
    """Thin persistence layer for session metadata and job history."""

    def __init__(self, session_root: Path) -> None:
        self.session_root = session_root
        self.session_root.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.session_root / "queue.json"
        if not self.queue_path.exists():
            self.queue_path.write_text(json.dumps({"jobs": []}, indent=2))

    # ------------------------------------------------------------------
    # Session metadata helpers
    # ------------------------------------------------------------------
    def session_dir(self, name: str) -> Path:
        return self.session_root / name

    def metadata_path(self, name: str) -> Path:
        return self.session_dir(name) / "metadata.json"

    def log_path(self, name: str) -> Path:
        return self.session_dir(name) / "console.log"

    def workspace_path(self, name: str) -> Path:
        return self.session_dir(name) / "artifacts"

    def list_sessions(self) -> List[SessionMetadata]:
        sessions: List[SessionMetadata] = []
        for metadata_file in sorted(self.session_root.glob("*/metadata.json")):
            try:
                payload = json.loads(metadata_file.read_text())
                sessions.append(SessionMetadata.from_dict(payload))
            except Exception:
                continue
        return sessions

    def load(self, name: str) -> Optional[SessionMetadata]:
        path = self.metadata_path(name)
        if not path.exists():
            return None
        payload = json.loads(path.read_text())
        return SessionMetadata.from_dict(payload)

    def save(self, metadata: SessionMetadata) -> None:
        metadata.ensure_paths()
        path = self.metadata_path(metadata.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata.to_dict(), indent=2))

    def delete(self, name: str) -> None:
        directory = self.session_dir(name)
        if directory.exists():
            shutil.rmtree(directory)

    # ------------------------------------------------------------------
    # Job tracking helpers
    # ------------------------------------------------------------------
    def _read_queue(self) -> Dict[str, Any]:
        return json.loads(self.queue_path.read_text())

    def _write_queue(self, payload: Dict[str, Any]) -> None:
        self.queue_path.write_text(json.dumps(payload, indent=2))

    def add_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        queue = self._read_queue()
        queue.setdefault("jobs", [])
        queue["jobs"].append(job)
        self._write_queue(queue)
        return job

    def update_job_status(self, job_id: str, status: SessionStatus, message: Optional[str] = None) -> None:
        queue = self._read_queue()
        mutated = False
        for job in queue.get("jobs", []):
            if job.get("id") == job_id:
                job["status"] = status
                job["updated_at"] = datetime.utcnow().strftime(ISO_FORMAT)
                if message:
                    job["message"] = message
                mutated = True
                break
        if mutated:
            self._write_queue(queue)

    def list_jobs(self) -> List[Dict[str, Any]]:
        queue = self._read_queue()
        return queue.get("jobs", [])

