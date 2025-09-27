from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from vibestack.sessions.models import SessionMetadata, SessionType
from vibestack.startup.sessions import StartupSessionSpec, ensure_startup_sessions


def _metadata(name: str, template: str) -> SessionMetadata:
    return SessionMetadata.from_dict(
        {
            "name": name,
            "template": template,
            "command": "python",
            "session_type": SessionType.LONG_RUNNING.value,
            "status": "running",
            "created_at": "2023-01-01T00:00:00.000Z",
            "updated_at": "2023-01-01T00:00:00.000Z",
            "log_path": f"/tmp/{name}.log",
            "workspace_path": f"/tmp/{name}",
        }
    )


class StubManager:
    def __init__(self, existing: Optional[Dict[str, SessionMetadata]] = None) -> None:
        self._sessions: Dict[str, SessionMetadata] = existing or {}
        self.created: List[Dict[str, Optional[str]]] = []

    def get_session(self, name: str) -> Optional[SessionMetadata]:
        return self._sessions.get(name)

    def create_session(
        self,
        name: str,
        *,
        template: str,
        command: Optional[str] = None,
        command_args: Optional[Sequence[str]] = None,
        description: Optional[str] = None,
    ) -> SessionMetadata:
        metadata = _metadata(name, template)
        self._sessions[name] = metadata
        self.created.append(
            {
                "name": name,
                "template": template,
                "command": command,
                "command_args": list(command_args) if command_args else None,
                "description": description,
            }
        )
        return metadata


def test_ensure_startup_sessions_creates_missing_sessions() -> None:
    manager = StubManager()
    spec = StartupSessionSpec(name="demo", template="bash", command="echo hi")

    result = ensure_startup_sessions(manager=manager, sessions=[spec])

    assert len(result) == 1
    assert result[0].name == "demo"
    assert manager.created[0]["command"] == "echo hi"


def test_ensure_startup_sessions_skips_existing_sessions() -> None:
    existing = _metadata("ready", "bash")
    manager = StubManager(existing={existing.name: existing})
    spec = StartupSessionSpec(name="ready", template="bash")

    result = ensure_startup_sessions(manager=manager, sessions=[spec])

    assert result == [existing]
    assert manager.created == []


def test_ensure_startup_sessions_handles_race_conditions() -> None:
    existing = _metadata("race", "bash")
    manager = StubManager()

    def create_session(**_: object) -> SessionMetadata:
        raise ValueError("already exists")

    manager.create_session = create_session  # type: ignore[assignment]
    manager._sessions[existing.name] = existing  # type: ignore[attr-defined]
    spec = StartupSessionSpec(name="race", template="bash")

    result = ensure_startup_sessions(manager=manager, sessions=[spec])

    assert result == [existing]
