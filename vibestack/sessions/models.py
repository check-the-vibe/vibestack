from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, Literal

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


class SessionType(str, Enum):
    """Supported tmux session lifecycles."""

    LONG_RUNNING = "long_running"
    ONE_OFF = "one_off"


SessionStatus = Literal[
    "queued",
    "starting",
    "running",
    "completed",
    "failed",
    "stopped",
]


@dataclass
class SessionMetadata:
    """Persistent metadata for a tmux-backed session."""

    name: str
    command: str
    template: str
    session_type: SessionType
    status: SessionStatus
    created_at: str
    updated_at: str
    log_path: str
    workspace_path: str
    description: Optional[str] = None
    job_id: Optional[str] = None
    exit_code: Optional[int] = None
    last_message: Optional[str] = None
    runtime: Dict[str, Any] = field(default_factory=dict, repr=False)

    schema_version: ClassVar[int] = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "command": self.command,
            "template": self.template,
            "session_type": self.session_type.value,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "log_path": self.log_path,
            "workspace_path": self.workspace_path,
            "description": self.description,
            "job_id": self.job_id,
            "exit_code": self.exit_code,
            "last_message": self.last_message,
        }

    def to_api_dict(self) -> Dict[str, Any]:
        payload = self.to_dict()
        if self.runtime:
            payload.update(self.runtime)
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SessionMetadata":
        return cls(
            name=payload["name"],
            command=payload.get("command", ""),
            template=payload.get("template", "custom"),
            session_type=SessionType(payload.get("session_type", SessionType.LONG_RUNNING.value)),
            status=payload.get("status", "queued"),
            created_at=payload.get("created_at", cls._utcnow()),
            updated_at=payload.get("updated_at", cls._utcnow()),
            log_path=payload.get("log_path", ""),
            workspace_path=payload.get("workspace_path", ""),
            description=payload.get("description"),
            job_id=payload.get("job_id"),
            exit_code=payload.get("exit_code"),
            last_message=payload.get("last_message"),
        )

    @staticmethod
    def _utcnow() -> str:
        return datetime.utcnow().strftime(ISO_FORMAT)

    def touch(self) -> None:
        self.updated_at = self._utcnow()

    def ensure_paths(self) -> None:
        """Ensure backing filesystem structure exists."""

        Path(self.workspace_path).mkdir(parents=True, exist_ok=True)
        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
