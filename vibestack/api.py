from __future__ import annotations

"""High-level API helpers for working with VibeStack sessions."""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import settings as vibestack_settings
from .sessions import SessionManager, SessionMetadata

_MANAGER: Optional[SessionManager] = None


def get_manager(session_root: Optional[str] = None) -> SessionManager:
    """Return a memoised :class:`SessionManager` instance."""
    global _MANAGER  # type: ignore[global-statement]
    if session_root or _MANAGER is None:
        _MANAGER = SessionManager(session_root=session_root)
    return _MANAGER


def _metadata_to_dict(metadata: SessionMetadata) -> Dict[str, Any]:
    payload = metadata.to_api_dict()
    payload["session_url"] = vibestack_settings.build_session_ui_url(
        metadata.name,
        template=metadata.template,
    )
    return payload


def list_sessions(session_root: Optional[str] = None) -> List[Dict[str, Any]]:
    manager = get_manager(session_root)
    return [_metadata_to_dict(meta) for meta in manager.list_sessions()]


def get_session(name: str, session_root: Optional[str] = None) -> Optional[Dict[str, Any]]:
    manager = get_manager(session_root)
    metadata = manager.get_session(name)
    return _metadata_to_dict(metadata) if metadata else None


def create_session(
    name: str,
    *,
    template: str = "bash",
    command: Optional[str] = None,
    command_args: Optional[List[str]] = None,
    working_dir: Optional[str] = None,
    description: Optional[str] = None,
    session_root: Optional[str] = None,
) -> Dict[str, Any]:
    manager = get_manager(session_root)
    metadata = manager.create_session(
        name,
        template=template,
        command=command,
        command_args=command_args,
        working_dir=working_dir,
        description=description,
    )
    return _metadata_to_dict(metadata)


def enqueue_one_off(
    name: str,
    command: str,
    *,
    template: str = "script",
    description: Optional[str] = None,
    session_root: Optional[str] = None,
) -> Dict[str, Any]:
    manager = get_manager(session_root)
    metadata = manager.enqueue_one_off(
        name,
        command,
        template=template,
        description=description,
    )
    return _metadata_to_dict(metadata)


def send_text(name: str, text: str, *, enter: bool = True, session_root: Optional[str] = None) -> None:
    manager = get_manager(session_root)
    manager.send_text(name, text, enter=enter)


def kill_session(name: str, session_root: Optional[str] = None) -> None:
    manager = get_manager(session_root)
    manager.kill_session(name)


def attach_session(name: str, session_root: Optional[str] = None) -> None:
    manager = get_manager(session_root)
    manager.attach_session(name)


def tail_log(name: str, *, lines: int = 200, session_root: Optional[str] = None) -> str:
    manager = get_manager(session_root)
    return manager.tail_log(name, lines=lines)


def list_jobs(session_root: Optional[str] = None) -> List[Dict[str, Any]]:
    manager = get_manager(session_root)
    return manager.list_jobs()


def list_templates() -> List[Dict[str, Any]]:
    manager = get_manager()
    return manager.list_templates()


def save_template(
    payload: Dict[str, Any],
    *,
    include_sources: Optional[Iterable[Path | str]] = None,
) -> str:
    manager = get_manager()
    include_paths: Optional[List[Path]] = None
    if include_sources is not None:
        include_paths = []
        for ref in include_sources:
            path = Path(ref)
            if path.exists() and path.is_file():
                include_paths.append(path)
    path = manager.save_template(payload, include_sources=include_paths)
    return str(path)


def delete_template(name: str) -> None:
    manager = get_manager()
    manager.delete_template(name)


__all__ = [
    "get_manager",
    "list_sessions",
    "get_session",
    "create_session",
    "enqueue_one_off",
    "send_text",
    "kill_session",
    "attach_session",
    "tail_log",
    "list_jobs",
    "list_templates",
    "save_template",
    "delete_template",
]
