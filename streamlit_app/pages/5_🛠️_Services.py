"""Supervisor service dashboard for Streamlit."""

from __future__ import annotations

import configparser
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import streamlit as st

from common import MANAGER, render_sidebar, sanitize_token, sync_state_from_query
from onboarding import render_onboarding_gate, render_onboarding_sidebar_controls

SUPERVISOR_CONFIG = Path(__file__).resolve().parents[2] / "supervisord.conf"
FLASH_STATE_KEY = "services_flash"


@dataclass
class ProgramMetadata:
    """Information parsed from supervisord.conf for a program."""

    name: str
    command: str
    stdout_logfile: Optional[str]
    stderr_logfile: Optional[str]


def push_flash(level: str, message: str) -> None:
    st.session_state[FLASH_STATE_KEY] = {"level": level, "message": message}


def display_flash() -> None:
    flash = st.session_state.pop(FLASH_STATE_KEY, None)
    if not flash:
        return
    message = flash.get("message")
    if not message:
        return
    level = (flash.get("level") or "info").lower()
    renderer = {
        "success": st.success,
        "error": st.error,
        "warning": st.warning,
        "info": st.info,
    }.get(level, st.info)
    renderer(message)


def load_program_metadata() -> Dict[str, ProgramMetadata]:
    config = configparser.ConfigParser(interpolation=None)
    programs: Dict[str, ProgramMetadata] = {}

    if not SUPERVISOR_CONFIG.exists():
        return programs

    config.read(SUPERVISOR_CONFIG)
    for section in config.sections():
        if not section.startswith("program:"):
            continue
        name = section.split(":", 1)[1]
        command = config.get(section, "command", fallback="")
        stdout_log = config.get(section, "stdout_logfile", fallback=None)
        stderr_log = config.get(section, "stderr_logfile", fallback=None)
        programs[name] = ProgramMetadata(
            name=name,
            command=command,
            stdout_logfile=stdout_log,
            stderr_logfile=stderr_log,
        )
    return programs


def fetch_supervisor_status() -> Tuple[Dict[str, Dict[str, str]], Optional[str]]:
    try:
        result = subprocess.run(
            ["sudo", "supervisorctl", "status"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - surfaced in UI
        error_output = exc.stderr or exc.stdout or str(exc)
        return {}, f"supervisorctl failed: {error_output.strip()}"
    except Exception as exc:  # pylint: disable=broad-except
        return {}, f"Unable to query supervisorctl: {exc}"

    status_map: Dict[str, Dict[str, str]] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        name = parts[0]
        state = parts[1]
        detail = parts[2] if len(parts) > 2 else ""

        pid_match = re.search(r"pid (\d+)", detail)
        uptime_match = re.search(
            r"uptime ([^,]+)" if "," in detail else r"uptime (.+)", detail
        )

        status_map[name] = {
            "state": state,
            "detail": detail,
            "pid": pid_match.group(1) if pid_match else "—",
            "uptime": uptime_match.group(1).strip() if uptime_match else "—",
        }

    return status_map, None


def session_name_for_service(name: str) -> str:
    token = sanitize_token(name, fallback="service")
    return f"tail-supervisor-{token}"


def kill_service_session(name: str) -> Tuple[bool, str]:
    session_name = session_name_for_service(name)
    try:
        metadata = MANAGER.get_session(session_name)
        MANAGER.kill_session(session_name)
    except Exception as exc:  # pylint: disable=broad-except
        return False, f"Unable to kill session '{session_name}': {exc}"

    if metadata:
        return True, f"Session '{session_name}' terminated."
    return True, f"Session '{session_name}' is not running."


def render_service_card(
    name: str,
    metadata: Optional[ProgramMetadata],
    status: Dict[str, str],
) -> None:
    service_token = sanitize_token(name, fallback="service")
    session_name = session_name_for_service(name)
    state = status.get("state", "unknown")
    pid = status.get("pid", "—")
    uptime = status.get("uptime", "—")
    detail = status.get("detail", "")
    command = metadata.command if metadata and metadata.command else ""

    with st.container():
        st.markdown(f"#### {name}")
        if detail:
            st.caption(detail)

        summary_cols = st.columns([1, 1, 1])
        summary_cols[0].metric("State", state)
        summary_cols[1].metric("PID", pid)
        summary_cols[2].metric("Uptime", uptime)

        if command:
            st.caption(f"Command: `{command}`")
        else:
            st.caption("Command: —")

        st.caption(f"tmux session: `{session_name}`")

        if st.button(
            "Kill session",
            key=f"kill_{service_token}",
            use_container_width=True,
        ):
            success, message = kill_service_session(name)
            push_flash("success" if success else "error", message)
            st.rerun()


def render_sidebar_navigation() -> None:
    render_sidebar(active_page="Services")
    render_onboarding_sidebar_controls()


st.set_page_config(page_title="Services", page_icon="🛠️", layout="wide")

sync_state_from_query()
render_sidebar_navigation()

if render_onboarding_gate():
    st.stop()

st.title("🛠️ Supervisor Services")
display_flash()

programs = load_program_metadata()
status_map, status_error = fetch_supervisor_status()

if status_error:
    st.error(status_error)

service_names = sorted(set(list(programs.keys()) + list(status_map.keys())))

if not service_names:
    st.info("No supervisor programs found to display.")
    st.stop()

if st.button(
    "🔄 Refresh Page",
    use_container_width=True,
    type="secondary",
    key="services_refresh_page",
):
    st.rerun()

columns_per_row = 3
for row_start in range(0, len(service_names), columns_per_row):
    row_names = service_names[row_start : row_start + columns_per_row]
    cols = st.columns(len(row_names))
    for col, service_name in zip(cols, row_names):
        metadata = programs.get(service_name)
        status = status_map.get(service_name, {})
        with col:
            render_service_card(service_name, metadata, status)
