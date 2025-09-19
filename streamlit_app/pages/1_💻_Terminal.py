import streamlit as st

from common import (
    KEY_ACTIVE_SESSION,
    KEY_ACTIVE_TEMPLATE,
    MANAGER,
    get_template_by_name,
    load_templates,
    list_sessions,
    render_sidebar,
    render_terminal,
    require_session,
    sync_state_from_query,
    update_query_params,
)

st.set_page_config(page_title="Terminal", page_icon="💻", layout="wide")

sync_state_from_query()
state = st.session_state

templates = load_templates()
sessions = list_sessions()
render_sidebar(active_page="Terminal", templates=templates, sessions=sessions)

active_template = get_template_by_name(templates, state.get(KEY_ACTIVE_TEMPLATE))
active_metadata = None

if state.get(KEY_ACTIVE_SESSION):
    try:
        active_metadata = MANAGER.get_session(state[KEY_ACTIVE_SESSION])
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Unable to load session '{state[KEY_ACTIVE_SESSION]}': {exc}")
        state[KEY_ACTIVE_SESSION] = None
        update_query_params()

st.title("💻 Terminal")

if not require_session(active_metadata):
    st.info("Once a session is active, you can interact with its tmux pane here.")
else:
    render_terminal(active_metadata)
