"""Onboarding helpers for the Streamlit entrypoint."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from common import MANAGER

SENTINEL_ENV = "VIBESTACK_ONBOARDING_SENTINEL"
DEFAULT_SENTINEL_RELATIVE = Path(".vibestack") / "onboarding_complete"
FLASH_STATE_KEY = "onboarding_flash"
VSCODE_SUPERVISOR_PROGRAM = "vscode-tunnel"


def _resolve_sentinel_path() -> Path:
    """Return the path Streamlit should use to store onboarding state."""

    env_override = os.environ.get(SENTINEL_ENV)
    if env_override:
        return Path(env_override).expanduser().resolve()

    base_home = os.environ.get("VIBESTACK_HOME")
    if base_home:
        root = Path(base_home)
    else:
        root = Path.home()
    return (root / DEFAULT_SENTINEL_RELATIVE).resolve()


def onboarding_complete() -> bool:
    return _resolve_sentinel_path().exists()


def mark_onboarding_complete() -> None:
    sentinel = _resolve_sentinel_path()
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("completed\n", encoding="utf-8")


def reset_onboarding() -> None:
    sentinel = _resolve_sentinel_path()
    try:
        sentinel.unlink()
    except FileNotFoundError:
        pass


def render_onboarding_sidebar_controls() -> None:
    """Expose onboarding toggles in the sidebar when appropriate."""

    with st.sidebar:
        if onboarding_complete():
            if st.button(
                "Re-open onboarding",
                key="onboarding_sidebar_reset",
                use_container_width=True,
            ):
                reset_onboarding()
                st.session_state[FLASH_STATE_KEY] = "Onboarding reset."
                st.rerun()
        else:
            st.info("Onboarding active — complete it to access sessions.")


def render_onboarding_gate() -> bool:
    """Render onboarding UI when needed.

    Returns ``True`` if onboarding is currently active and the caller should
    halt further rendering for the page until the user completes or dismisses
    the flow.
    """

    flash_message = st.session_state.pop(FLASH_STATE_KEY, None)
    if flash_message:
        st.success(flash_message)

    if onboarding_complete():
        return False

    sentinel_path = _resolve_sentinel_path()
    st.title("👋 Welcome to VibeStack")
    st.write("Welcome to Vibestack, we're happy to have you.")

    button_cols = st.columns([1, 1, 2])
    tail_clicked = button_cols[0].button(
        "Open VS Code Logs",
        key="onboarding_tail_vscode",
        help="Launch a new session that tails the VS Code tunnel service logs.",
        use_container_width=True,
    )

    if tail_clicked:
        success, message = _launch_vscode_log_session()
        if success:
            st.session_state[FLASH_STATE_KEY] = message
            st.rerun()
        else:
            st.error(message)

    close_clicked = button_cols[1].button(
        "Close",
        key="onboarding_close",
        help="Mark onboarding complete and continue to the dashboard.",
        use_container_width=True,
        type="primary",
    )

    if close_clicked:
        mark_onboarding_complete()
        st.session_state[FLASH_STATE_KEY] = "Onboarding complete."
        st.rerun()

    return True


def _launch_vscode_log_session() -> tuple[bool, str]:
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    session_name = f"tail-{VSCODE_SUPERVISOR_PROGRAM}-{timestamp}"
    command = f"python -m vibestack.scripts.supervisor_tail --program {VSCODE_SUPERVISOR_PROGRAM}"
    try:
        metadata = MANAGER.create_session(
            session_name,
            template="script",
            command=command,
            description="Follow VS Code tunnel logs",
        )
    except Exception as exc:  # pylint: disable=broad-except
        return False, f"Unable to launch log session: {exc}"

    return True, f"Session '{metadata.name}' created to follow VS Code tunnel logs."
