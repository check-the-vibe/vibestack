import streamlit as st

from common import (
    load_templates,
    render_sidebar,
    render_template_admin,
    sync_state_from_query,
)
from onboarding import render_onboarding_sidebar_controls

st.set_page_config(page_title="Templates", page_icon="⚙️", layout="wide")

sync_state_from_query()

templates = load_templates()
render_sidebar(active_page="Templates")
render_onboarding_sidebar_controls()

st.title("⚙️ Templates & Assets")
render_template_admin(templates)
