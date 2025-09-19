import streamlit as st

from common import (
    load_templates,
    list_sessions,
    render_sidebar,
    render_template_admin,
    sync_state_from_query,
)

st.set_page_config(page_title="Templates", page_icon="⚙️", layout="wide")

sync_state_from_query()

templates = load_templates()
sessions = list_sessions()
# Templates page does not require active session, but we keep the sidebar
# selectors available so navigation stays consistent.
render_sidebar(active_page="Templates", templates=templates, sessions=sessions)

st.title("⚙️ Templates & Assets")
render_template_admin(templates)
