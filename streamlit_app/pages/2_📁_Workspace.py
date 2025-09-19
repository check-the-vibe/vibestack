import streamlit as st

from common import (
    KEY_ACTIVE_SESSION,
    KEY_ACTIVE_TEMPLATE,
    MANAGER,
    get_template_by_name,
    load_templates,
    list_sessions,
    render_sidebar,
    render_template_conversion,
    render_workspace_editor,
    require_session,
    sync_state_from_query,
    update_query_params,
)

st.set_page_config(page_title="Workspace", page_icon="📁", layout="wide")

sync_state_from_query()
state = st.session_state

templates = load_templates()
sessions = list_sessions()
render_sidebar(active_page="Workspace", templates=templates, sessions=sessions)

active_template = get_template_by_name(templates, state.get(KEY_ACTIVE_TEMPLATE))
active_metadata = None

if state.get(KEY_ACTIVE_SESSION):
    try:
        active_metadata = MANAGER.get_session(state[KEY_ACTIVE_SESSION])
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Unable to load session '{state[KEY_ACTIVE_SESSION]}': {exc}")
        state[KEY_ACTIVE_SESSION] = None
        update_query_params()

st.title("📁 Workspace")

if not require_session(active_metadata):
    st.info("Pick a session to browse and edit its files.")
else:
    render_workspace_editor(active_metadata)
    st.divider()
    render_template_conversion(active_metadata, active_template)
