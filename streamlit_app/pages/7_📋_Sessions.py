import streamlit as st

from common import (
    INACTIVE_STATUSES,
    KEY_ACTIVE_SESSION,
    KEY_ACTIVE_TEMPLATE,
    MANAGER,
    load_templates,
    list_sessions,
    render_sidebar,
    sync_state_from_query,
    update_query_params,
)

st.set_page_config(page_title="Sessions", page_icon="📋", layout="wide")

sync_state_from_query()

templates = load_templates()
sessions = list_sessions()
render_sidebar(active_page="Sessions", templates=templates, sessions=sessions)

st.title("📋 All Sessions")

if not sessions:
    st.info("No sessions have been created yet.")
    st.stop()

rows = []
for item in sessions:
    status = item.status or ""
    rows.append(
        {
            "Name": item.name,
            "Template": item.template,
            "Status": status,
            "Created": item.created_at,
            "Updated": item.updated_at,
            "Type": item.session_type.value if item.session_type else "",
        }
    )

st.dataframe(rows, use_container_width=True, hide_index=True)

st.subheader("Session Actions")
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
        focus_disabled = inactive
        kill_disabled = inactive
        cols = st.columns(2)
        if cols[0].button(
            "Focus in dashboard",
            disabled=focus_disabled,
            key=f"focus_{meta.name}",
        ):
            st.session_state[KEY_ACTIVE_SESSION] = meta.name
            st.session_state[KEY_ACTIVE_TEMPLATE] = meta.template
            update_query_params()
            st.switch_page("app.py")
        if cols[1].button(
            "Kill session",
            disabled=kill_disabled,
            key=f"kill_{meta.name}_sessions_page",
        ):
            try:
                MANAGER.kill_session(meta.name)
            except Exception as exc:  # pylint: disable=broad-except
                st.error(f"Unable to kill session: {exc}")
            else:
                st.success(f"Session '{meta.name}' terminated.")
                st.rerun()
