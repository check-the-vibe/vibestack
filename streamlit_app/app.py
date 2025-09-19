import streamlit as st

from common import (
    KEY_ACTIVE_SESSION,
    KEY_ACTIVE_TEMPLATE,
    MANAGER,
    get_template_by_name,
    load_templates,
    list_sessions,
    render_session_overview,
    render_sidebar,
    require_session,
    sync_state_from_query,
    update_query_params,
)

st.set_page_config(
    page_title="VibeStack Control Center",
    page_icon="🚀",
    layout="wide",
)

sync_state_from_query()

state = st.session_state

templates = load_templates()
sessions = list_sessions()
render_sidebar(active_page="Session", templates=templates, sessions=sessions)

active_template = get_template_by_name(templates, state.get(KEY_ACTIVE_TEMPLATE))
active_metadata = None

if state.get(KEY_ACTIVE_SESSION):
    try:
        active_metadata = MANAGER.get_session(state[KEY_ACTIVE_SESSION])
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Unable to load session '{state[KEY_ACTIVE_SESSION]}': {exc}")
        state[KEY_ACTIVE_SESSION] = None
        update_query_params()
    else:
        if active_metadata and active_metadata.template and state.get(KEY_ACTIVE_TEMPLATE) != active_metadata.template:
            state[KEY_ACTIVE_TEMPLATE] = active_metadata.template
            active_template = get_template_by_name(templates, state.get(KEY_ACTIVE_TEMPLATE))
            update_query_params()

st.title("🚀 VibeStack Session Control Center")

if not templates:
    st.info("No templates available. Visit the Templates page to add one.")
elif not sessions:
    st.info("Launch a session, then revisit this page.")
elif not require_session(active_metadata):
    pass
else:
    render_session_overview(active_metadata, active_template)
