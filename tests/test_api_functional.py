"""Functional tests for the high-level VibeStack API.

These tests exercise the real session manager and tmux integration using
simple shell commands so we can spot regressions surfaced through the MCP
stack quickly.
"""

from __future__ import annotations

import time
import uuid
from typing import Iterator

import pytest

from vibestack import api as vibestack_api


@pytest.fixture(autouse=True)
def reset_manager() -> Iterator[None]:
    """Ensure each test gets a fresh SessionManager instance."""

    vibestack_api._MANAGER = None  # type: ignore[attr-defined]
    try:
        yield
    finally:
        vibestack_api._MANAGER = None  # type: ignore[attr-defined]


@pytest.fixture
def session_root(tmp_path_factory: pytest.TempPathFactory) -> str:
    root = tmp_path_factory.mktemp("sessions")
    return str(root)


def _wait_for_completion(name: str, session_root: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last_session: dict | None = None
    while time.time() < deadline:
        session = vibestack_api.get_session(name, session_root=session_root)
        if session and session.get("status") in {"completed", "failed"}:
            last_session = session
            break
        time.sleep(0.2)
    if not last_session:
        raise AssertionError(f"session '{name}' did not finish within {timeout} seconds")
    return last_session


def test_enqueue_one_off_captures_stdout(session_root: str) -> None:
    """One-off jobs should persist their stdout so the MCP stack can read it."""

    session_name = f"pytest-{uuid.uuid4().hex[:8]}"
    command = "printf 'hello-from-test\\n'"

    vibestack_api.enqueue_one_off(
        session_name,
        command,
        session_root=session_root,
    )

    session = _wait_for_completion(session_name, session_root)

    deadline = time.time() + 10.0
    log_output = ""
    while time.time() < deadline:
        log_output = vibestack_api.tail_log(session_name, session_root=session_root)
        if "hello-from-test" in log_output:
            break
        time.sleep(0.2)

    vibestack_api.kill_session(session_name, session_root=session_root)

    assert session["status"] == "completed"
    assert session.get("exit_code") == 0
    session_url = session.get("session_url")
    assert session_url and session_name in session_url
    assert "hello-from-test" in log_output
