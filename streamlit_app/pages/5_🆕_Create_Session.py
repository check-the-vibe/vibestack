import streamlit as st

from common import (
    KEY_ACTIVE_TEMPLATE,
    get_template_by_name,
    load_templates,
    render_create_session_form,
    render_sidebar,
    sync_state_from_query,
)

st.set_page_config(page_title="Create Session", page_icon="🆕", layout="wide")

sync_state_from_query()
state = st.session_state

templates = load_templates()
render_sidebar(active_page="Create", templates=templates, sessions=[])

selected_template = get_template_by_name(templates, state.get(KEY_ACTIVE_TEMPLATE))

st.title("🆕 Create Session")
render_create_session_form(templates, selected_template)
