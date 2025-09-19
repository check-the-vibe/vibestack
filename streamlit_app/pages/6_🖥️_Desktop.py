import os

import streamlit as st
from streamlit.components.v1 import iframe

from common import load_templates, list_sessions, render_sidebar, sync_state_from_query

st.set_page_config(page_title="Desktop", page_icon="🖥️", layout="wide")

sync_state_from_query()

templates = load_templates()
sessions = list_sessions()
render_sidebar(active_page="Desktop", templates=templates, sessions=sessions)

st.title("🖥️ Remote Desktop")
desktop_url = os.environ.get("VIBESTACK_DESKTOP_BASE", "/computer/")
iframe(src=desktop_url, height=800)
st.caption("Interact with the noVNC desktop. If the iframe is unresponsive, open it in a new tab.")
st.markdown(f"[Open desktop in new tab]({desktop_url})")
