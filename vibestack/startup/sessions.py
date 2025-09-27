"""Helpers for provisioning startup tmux sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from vibestack import api as vibestack_api
from vibestack.sessions import SessionManager, SessionMetadata


@dataclass(frozen=True)
class StartupSessionSpec:
    """Declarative description of a startup session."""

    name: str
    template: str = "bash"
    command: Optional[str] = None
    command_args: Optional[Sequence[str]] = None
    description: Optional[str] = None


def ensure_startup_sessions(
    *,
    manager: Optional[SessionManager] = None,
    sessions: Optional[Iterable[StartupSessionSpec]] = None,
) -> List[SessionMetadata]:
    """Create any missing startup sessions and return their metadata."""

    resolved_manager = manager or vibestack_api.get_manager()
    resolved_specs = list(sessions or DEFAULT_STARTUP_SESSIONS)
    results: List[SessionMetadata] = []

    for spec in resolved_specs:
        existing = resolved_manager.get_session(spec.name)
        if existing:
            results.append(existing)
            continue

        try:
            created = resolved_manager.create_session(
                spec.name,
                template=spec.template,
                command=spec.command,
                command_args=list(spec.command_args) if spec.command_args else None,
                description=spec.description,
            )
        except ValueError:
            fallback = resolved_manager.get_session(spec.name)
            if fallback:
                results.append(fallback)
            continue
        results.append(created)

    return results


DEFAULT_STARTUP_SESSIONS: List[StartupSessionSpec] = [
    StartupSessionSpec(
        name="startup-supervisor-logs",
        template="startup-supervisor-logs",
        description="Browse supervisord logs with a simple TUI.",
    )
]


__all__ = [
    "DEFAULT_STARTUP_SESSIONS",
    "StartupSessionSpec",
    "ensure_startup_sessions",
]
