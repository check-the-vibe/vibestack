"""Model Context Protocol configuration surface."""
from __future__ import annotations

import streamlit as st

from common import (
    KEY_ACTIVE_SESSION,
    ensure_state_defaults,
    list_sessions,
    render_sidebar,
    sync_state_from_query,
)
from vibestack import settings as vibestack_settings

sync_state_from_query()
ensure_state_defaults()
sessions = list_sessions()
render_sidebar(active_page="MCP", sessions=sessions)

st.title("Model Context Protocol")
st.write(
    "Adjust the base URL used when MCP tools generate links back to the Streamlit Sessions page."
)

current_base = vibestack_settings.get_session_base_url()

with st.form("mcp_base_url"):
    base_url = st.text_input(
        "Public base URL",
        value=current_base,
        placeholder="https://example.ngrok.app",
        help=(
            "Domain prepended to /ui/Sessions when generating session links. "
            "Codex MCP tools will read this value instantly."
        ),
    )
    submitted = st.form_submit_button("Save")
    if submitted:
        vibestack_settings.set_session_base_url(base_url)
        st.success("Updated MCP base URL.")
        current_base = vibestack_settings.get_session_base_url()

active_session = st.session_state.get(KEY_ACTIVE_SESSION)
preview_session = active_session or "example-session"
preview_url = vibestack_settings.build_session_ui_url(preview_session)

st.markdown("### Preview")
st.caption(
    "Active session preview shown when available; otherwise an example value is used."
)
st.code(preview_url, language="text")

if not active_session:
    st.info(
        "Select a session from the Sessions page to preview the exact link MCP tools will return."
    )

st.markdown("---")
st.caption(
    "Changes are stored under ~/.vibestack/settings.json. Override the value with "
    "the VIBESTACK_SESSION_FOLLOW_BASE environment variable when needed."
)
