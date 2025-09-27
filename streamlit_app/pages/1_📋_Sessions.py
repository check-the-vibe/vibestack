import streamlit as st
from pathlib import Path

from common import (
    INACTIVE_STATUSES,
    KEY_ACTIVE_SESSION,
    KEY_TEMPLATE_PAGE_PREFIX,
    MANAGER,
    filter_active_sessions,
    find_streamlit_pages,
    get_template_by_name,
    load_templates,
    list_sessions,
    render_create_session_form,
    render_dynamic_streamlit_page,
    render_session_overview,
    render_sidebar,
    render_template_conversion,
    render_terminal,
    render_workspace_editor,
    sync_state_from_query,
    update_query_params,
)
from onboarding import render_onboarding_gate, render_onboarding_sidebar_controls

st.set_page_config(page_title="Sessions", page_icon="📋", layout="wide")

sync_state_from_query()
state = st.session_state
state.setdefault("show_create_session_form", False)

templates = load_templates()
sessions = list_sessions()
render_sidebar(active_page="Sessions")
render_onboarding_sidebar_controls()

if render_onboarding_gate():
    st.stop()

st.title("📋 Sessions")

session_lookup = {meta.name: meta for meta in sessions}
active_session_name = state.get(KEY_ACTIVE_SESSION)
if active_session_name not in session_lookup:
    active_session_name = None
    state[KEY_ACTIVE_SESSION] = None

if not active_session_name and sessions:
    preferred = next((meta.name for meta in sessions if (meta.status or "").lower() not in INACTIVE_STATUSES), None)
    if preferred:
        state[KEY_ACTIVE_SESSION] = preferred
        update_query_params()
        active_session_name = preferred

active_sessions = filter_active_sessions(sessions)
option_values = [None] + [meta.name for meta in active_sessions]
label_lookup = {None: "— Select session —"}
for meta in active_sessions:
    label_lookup[meta.name] = f"{meta.template or '—'} · {meta.name} · {meta.status}"

if active_session_name and active_session_name not in option_values:
    active_session_name = None
    state[KEY_ACTIVE_SESSION] = None
    update_query_params()

current_index = option_values.index(active_session_name) if active_session_name in option_values else 0
selected_name = st.selectbox(
    "Active session",
    options=option_values,
    index=current_index,
    format_func=lambda name: label_lookup.get(name, name or ""),
    key="sessions_active_select",
)

if selected_name != active_session_name:
    state[KEY_ACTIVE_SESSION] = selected_name
    update_query_params()
    active_session_name = selected_name

show_form = state.get("show_create_session_form", False)
if not sessions:
    show_form = True

active_template = None
if active_session_name:
    meta = session_lookup.get(active_session_name)
    if meta and meta.template:
        active_template = get_template_by_name(templates, meta.template)

with st.expander("Create a session", expanded=show_form):
    render_create_session_form(templates, active_template)

active_metadata = None
if active_session_name:
    try:
        active_metadata = MANAGER.get_session(active_session_name)
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Unable to load session '{active_session_name}': {exc}")
        state[KEY_ACTIVE_SESSION] = None
        update_query_params()
        active_metadata = None

if not sessions:
    st.info("No sessions created yet. Use the form above to launch your first workspace.")
elif not active_metadata:
    st.info("Select a session from the dropdown to view details, or create a new one.")
else:
    active_template = get_template_by_name(templates, active_metadata.template)
    overview_tab, terminal_tab, workspace_tab, ui_tab = st.tabs(["Overview", "Terminal", "Workspace", "Template UI"])

    with overview_tab:
        render_session_overview(active_metadata, active_template)

    with terminal_tab:
        render_terminal(active_metadata)

    with workspace_tab:
        render_workspace_editor(active_metadata)
        st.divider()
        render_template_conversion(active_metadata, active_template)

    with ui_tab:
        workspace = Path(active_metadata.workspace_path)
        pages = find_streamlit_pages(workspace)
        if not pages:
            st.info("No Streamlit pages found in this workspace.")
        else:
            labels = [str(page.relative_to(workspace)) for page in pages]
            lookup = dict(zip(labels, pages))
            state_key = f"{KEY_TEMPLATE_PAGE_PREFIX}{active_metadata.name}"
            default_label = state.get(state_key, labels[0])
            if default_label not in lookup:
                default_label = labels[0]
            selected_label = st.selectbox("Template page", labels, index=labels.index(default_label))
            state[state_key] = selected_label
            render_dynamic_streamlit_page(lookup[selected_label], active_metadata)

st.divider()
st.subheader("Session registry")

if not sessions:
    st.info("Session history will appear here once sessions are launched.")
else:
    rows = []
    for item in sessions:
        rows.append(
            {
                "Name": item.name,
                "Template": item.template,
                "Status": item.status,
                "Created": item.created_at,
                "Updated": item.updated_at,
                "Type": item.session_type.value if item.session_type else "",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Manage sessions")
    for meta in sessions:
        status = (meta.status or "").lower()
        inactive = status in INACTIVE_STATUSES
        with st.expander(f"{meta.name} — {meta.status}", expanded=False):
            st.write(
                {
                    "template": meta.template,
                    "status": meta.status,
                    "created_at": meta.created_at,
                    "updated_at": meta.updated_at,
                    "description": meta.description,
                    "command": meta.command,
                    "session_type": meta.session_type.value if meta.session_type else None,
                    "workspace_path": meta.workspace_path,
                    "log_path": meta.log_path,
                }
            )
            cols = st.columns(2)
            if cols[0].button(
                "Focus in view",
                disabled=inactive,
                key=f"focus_{meta.name}",
            ):
                state[KEY_ACTIVE_SESSION] = meta.name
                update_query_params()
                st.rerun()
            if cols[1].button(
                "Kill session",
                disabled=inactive,
                key=f"kill_{meta.name}_registry",
            ):
                try:
                    MANAGER.kill_session(meta.name)
                except Exception as exc:  # pylint: disable=broad-except
                    st.error(f"Unable to kill session: {exc}")
                else:
                    st.success(f"Session '{meta.name}' terminated.")
                    st.rerun()
