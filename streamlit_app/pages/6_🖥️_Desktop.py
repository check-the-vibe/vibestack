import os

import streamlit as st
from streamlit.components.v1 import iframe

from common import render_sidebar, sync_state_from_query
from onboarding import render_onboarding_gate, render_onboarding_sidebar_controls

st.set_page_config(page_title="Desktop", page_icon="🖥️", layout="wide")

sync_state_from_query()

render_sidebar(active_page="Desktop")
render_onboarding_sidebar_controls()

if render_onboarding_gate():
    st.stop()

st.title("🖥️ Remote Desktop")
desktop_url = os.environ.get("VIBESTACK_DESKTOP_BASE", "/computer/")
iframe(src=desktop_url, height=800)
st.caption("Interact with the noVNC desktop. If the iframe is unresponsive, open it in a new tab.")
st.markdown(f"[Open desktop in new tab]({desktop_url})")
