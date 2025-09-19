from pathlib import Path

import streamlit as st

from common import (
    KEY_ACTIVE_SESSION,
    KEY_ACTIVE_TEMPLATE,
    MANAGER,
    find_streamlit_pages,
    get_template_by_name,
    render_dynamic_streamlit_page,
    load_templates,
    list_sessions,
    render_sidebar,
    require_session,
    sync_state_from_query,
    update_query_params,
)

st.set_page_config(page_title="Template UI", page_icon="🧩", layout="wide")

sync_state_from_query()
state = st.session_state

templates = load_templates()
sessions = list_sessions()
render_sidebar(active_page="UI", templates=templates, sessions=sessions)

active_template = get_template_by_name(templates, state.get(KEY_ACTIVE_TEMPLATE))
active_metadata = None

if state.get(KEY_ACTIVE_SESSION):
    try:
        active_metadata = MANAGER.get_session(state[KEY_ACTIVE_SESSION])
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Unable to load session '{state[KEY_ACTIVE_SESSION]}': {exc}")
        state[KEY_ACTIVE_SESSION] = None
        update_query_params()

st.title("🧩 Template UI")

if not require_session(active_metadata):
    st.info("Pick a session to load template-specific pages.")
else:
    workspace = Path(active_metadata.workspace_path)
    pages = find_streamlit_pages(workspace)
    if not pages:
        st.info("No Streamlit pages found in this workspace.")
    else:
        labels = [str(page.relative_to(workspace)) for page in pages]
        lookup = {label: page for label, page in zip(labels, pages)}
        state_key = f"template_page_{active_metadata.name}"
        default_label = state.get(state_key)
        if default_label not in lookup:
            default_label = labels[0]
        selected_label = st.selectbox("Select a template page", labels, index=labels.index(default_label))
        state[state_key] = selected_label
        render_dynamic_streamlit_page(lookup[selected_label], active_metadata)
