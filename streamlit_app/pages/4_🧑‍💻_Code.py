import streamlit as st

from common import ensure_supervisor_tail_session, render_sidebar, render_terminal, sync_state_from_query
from onboarding import render_onboarding_sidebar_controls

st.set_page_config(page_title="Code", page_icon="🧑‍💻", layout="wide")

sync_state_from_query()

render_sidebar(active_page="Code")
render_onboarding_sidebar_controls()

st.title("🧑‍💻 Code Tunnel")
st.caption("Open the VibeStack VS Code tunnel in a separate tab to start coding.")
st.markdown("[Launch VS Code tunnel](https://vscode.dev/tunnel/vibestack)")

st.divider()
st.subheader("VS Code Tunnel Logs")
st.caption("Live tail from supervisor for the VS Code tunnel service.")
session_metadata = ensure_supervisor_tail_session("vscode-tunnel")
if session_metadata:
    render_terminal(session_metadata, allow_input=False, height=480)
else:
    st.error("Unable to load VS Code tunnel logs right now.")
