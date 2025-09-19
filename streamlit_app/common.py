"""Shared helpers for Streamlit pages in VibeStack."""
from __future__ import annotations

import json
import math
import os
import runpy
import sys
import urllib.parse
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import streamlit as st
from streamlit.components.v1 import iframe

from vibestack.sessions import SessionManager, SessionMetadata
from vibestack.sessions.models import ISO_FORMAT

# Instantiate a single session manager for all pages.
MANAGER = SessionManager()

# Keys stored in session state.
KEY_ACTIVE_TEMPLATE = "active_template"
KEY_ACTIVE_SESSION = "active_session"
KEY_SIDEBAR_SESSION = "sidebar_session_choice"
KEY_WORKSPACE_FILE_PREFIX = "workspace_file_"
KEY_TEMPLATE_PAGE_PREFIX = "template_page_"
INACTIVE_STATUSES: Set[str] = {
    "stopped",
    "dead",
    "finished",
    "completed",
    "failed",
    "killed",
    "terminated",
    "exited",
}


def ensure_state_defaults() -> None:
    state = st.session_state
    state.setdefault(KEY_ACTIVE_TEMPLATE, None)
    state.setdefault(KEY_ACTIVE_SESSION, None)


def load_templates() -> List[Dict[str, Any]]:
    MANAGER.refresh_templates()
    return MANAGER.list_templates()


def list_sessions() -> List[SessionMetadata]:
    try:
        return MANAGER.list_sessions()
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Unable to list sessions: {exc}")
        return []


def get_template_label(template: Dict[str, Any]) -> str:
    return template.get("label") or template.get("name", "")


def get_template_by_name(templates: Iterable[Dict[str, Any]], name: Optional[str]) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    for template in templates:
        if template.get("name") == name:
            return template
    return None


def filter_active_sessions(sessions: Iterable[SessionMetadata]) -> List[SessionMetadata]:
    results: List[SessionMetadata] = []
    for meta in sessions:
        status = (meta.status or "").lower()
        if status in INACTIVE_STATUSES:
            continue
        results.append(meta)
    return results


def sessions_for_template(sessions: Iterable[SessionMetadata], template_name: Optional[str]) -> List[SessionMetadata]:
    relevant = filter_active_sessions(sessions)
    if not template_name:
        return relevant
    return [meta for meta in relevant if meta.template == template_name]


def sync_state_from_query() -> None:
    ensure_state_defaults()
    params = st.query_params
    template_from_query = params.get("template")
    if isinstance(template_from_query, list):
        template_from_query = template_from_query[-1]
    session_from_query = params.get("session")
    if isinstance(session_from_query, list):
        session_from_query = session_from_query[-1]

    state = st.session_state
    changed = False
    if template_from_query and state.get(KEY_ACTIVE_TEMPLATE) != template_from_query:
        state[KEY_ACTIVE_TEMPLATE] = template_from_query
        changed = True
    if session_from_query and state.get(KEY_ACTIVE_SESSION) != session_from_query:
        state[KEY_ACTIVE_SESSION] = session_from_query
        changed = True
    if changed:
        # Keep sidebar selectors in sync on rerun.
        state[KEY_SIDEBAR_SESSION] = state.get(KEY_ACTIVE_SESSION)


def update_query_params() -> None:
    params: Dict[str, str] = {}
    state = st.session_state
    template = state.get(KEY_ACTIVE_TEMPLATE)
    session = state.get(KEY_ACTIVE_SESSION)
    if template:
        params["template"] = template
    if session:
        params["session"] = session
    query = st.query_params
    query.clear()
    if params:
        query.update(params)


def render_sidebar(*, active_page: str, templates: List[Dict[str, Any]], sessions: List[SessionMetadata]) -> None:
    state = st.session_state
    ensure_state_defaults()

    with st.sidebar:
        st.markdown(
            """
            <style>
            [data-testid="stSidebarNav"] {display: none;}
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.subheader("Navigation")
        st.page_link("app.py", label="Session", icon="📡")
        st.page_link("pages/1_💻_Terminal.py", label="Terminal", icon="💻")
        st.page_link("pages/2_📁_Workspace.py", label="Workspace", icon="📁")
        st.page_link("pages/3_🧩_UI.py", label="UI", icon="🧩")

        if templates:
            template_names = [tpl["name"] for tpl in templates]
            if state.get(KEY_ACTIVE_TEMPLATE) not in template_names:
                state[KEY_ACTIVE_TEMPLATE] = template_names[0]
        else:
            state[KEY_ACTIVE_TEMPLATE] = None
            st.info("Add templates to get started.")

        active_sessions = filter_active_sessions(sessions)
        session_lookup = {meta.name: meta for meta in active_sessions}
        if session_lookup:
            options: List[Optional[str]] = [None] + list(session_lookup.keys())
            current = state.get(KEY_ACTIVE_SESSION)
            if current not in session_lookup:
                current = None
                state[KEY_ACTIVE_SESSION] = None

            default_index = options.index(current) if current in options else 0

            def session_label(value: Optional[str]) -> str:
                if value is None:
                    return "Select a session"
                meta = session_lookup.get(value)
                template_name = meta.template if meta and meta.template else "—"
                return f"{template_name} · {value}" if meta else value

            selected_session = st.selectbox(
                "Session",
                options=options,
                index=default_index,
                format_func=session_label,
                key=KEY_SIDEBAR_SESSION,
            )
            if selected_session != state.get(KEY_ACTIVE_SESSION):
                state[KEY_ACTIVE_SESSION] = selected_session
                if selected_session:
                    meta = session_lookup.get(selected_session)
                    if meta and meta.template:
                        state[KEY_ACTIVE_TEMPLATE] = meta.template
                update_query_params()
                st.rerun()
        else:
            st.caption("No active sessions available yet.")
            state[KEY_ACTIVE_SESSION] = None

        create_disabled = not templates
        if st.button("Create a Session", use_container_width=True, disabled=create_disabled):
            st.switch_page("pages/5_🆕_Create_Session.py")

        st.markdown("---")
        st.page_link("pages/4_⚙️_Templates.py", label="Templates", icon="⚙️")
        st.page_link("pages/6_🖥️_Desktop.py", label="Desktop", icon="🖥️")
        st.page_link("pages/7_📋_Sessions.py", label="Sessions", icon="📋")


def require_session(metadata: Optional[SessionMetadata]) -> bool:
    if metadata:
        return True
    st.info("Select a session from the sidebar to continue.")
    return False


def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, ISO_FORMAT)
    except ValueError:
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None


def format_timestamp(value: Optional[str]) -> str:
    parsed = _parse_iso_timestamp(value)
    if not parsed:
        return "—"
    return parsed.strftime("%Y-%m-%d %H:%M:%S UTC")


def filter_visible_files(root: Path, limit: int = 200) -> List[Path]:
    if not root.exists():
        return []
    files: List[Path] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= limit:
            break
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts):
            files.append(path)
    return files


@contextmanager
def temporary_sys_path(entry: str):
    added = False
    if entry and entry not in sys.path:
        sys.path.insert(0, entry)
        added = True
    try:
        yield
    finally:
        if added and entry in sys.path:
            sys.path.remove(entry)


def find_streamlit_pages(root: Path) -> List[Path]:
    pages_dir = root / "streamlit"
    if not pages_dir.exists() or not pages_dir.is_dir():
        return []
    return sorted([path for path in pages_dir.rglob("*.py") if path.is_file()])


def render_dynamic_streamlit_page(page_path: Path, metadata: SessionMetadata) -> None:
    init_globals = {
        "st": st,
        "session_metadata": metadata,
        "session_workspace": Path(metadata.workspace_path),
    }
    with temporary_sys_path(str(page_path.parent)), st.spinner(f"Loading {page_path.name}..."):
        try:
            runpy.run_path(str(page_path), init_globals=init_globals)
        except Exception as exc:  # pylint: disable=broad-except
            st.error(f"Failed to render {page_path.name}: {exc}")
            st.exception(exc)


def render_terminal(metadata: SessionMetadata) -> None:
    with st.form(f"send_input_{metadata.name}"):
        text = st.text_input("Send text to terminal", placeholder="Type a command")
        submitted = st.form_submit_button("Send", use_container_width=True)
        if submitted:
            if not text:
                st.warning("Nothing to send.")
            else:
                try:
                    MANAGER.send_text(metadata.name, text, enter=False)
                    MANAGER.send_text(metadata.name, "", enter=True)
                except Exception as exc:  # pylint: disable=broad-except
                    st.error(f"Unable to send text: {exc}")
                else:
                    st.success("Sent to session.")
                    st.rerun()

    query = urllib.parse.urlencode(
        [("arg", "session"), ("arg", metadata.name), ("arg", metadata.template)]
    )
    iframe_url = os.environ.get("VIBESTACK_TTYD_BASE", "/terminal/")
    iframe(src=f"{iframe_url}?{query}", height=600)
    st.caption("Open in a new tab:")
    st.markdown(
        f"[Launch terminal](../terminal/?{query})",
        help="Open the tmux session in a dedicated browser tab.",
    )


def render_workspace_editor(metadata: SessionMetadata) -> None:
    workspace = Path(metadata.workspace_path)
    if not workspace.exists():
        st.info("Workspace directory is empty.")
        return

    files = filter_visible_files(workspace)
    if not files:
        st.info("No files created yet.")
        return

    relative_names = [str(path.relative_to(workspace)) for path in files]
    state_key = f"{KEY_WORKSPACE_FILE_PREFIX}{metadata.name}"
    state = st.session_state
    default_index = 0
    if state_key in state:
        try:
            default_index = relative_names.index(state[state_key])
        except ValueError:
            default_index = 0
    selected_rel = st.selectbox("Select a file", relative_names, index=default_index)
    state[state_key] = selected_rel
    file_path = workspace / selected_rel

    try:
        content = file_path.read_text()
        binary = False
    except UnicodeDecodeError:
        binary = True
        content = file_path.read_bytes()

    if binary:
        st.warning("Binary file preview only. Download to inspect.")
        st.download_button("Download", data=content, file_name=file_path.name)
        return

    with st.form(f"edit_{metadata.name}_{selected_rel}"):
        edited = st.text_area("File contents", content, height=400)
        if st.form_submit_button("Save", use_container_width=True):
            file_path.write_text(edited)
            st.success("File saved.")
    st.caption(f"Path: {file_path}")


def render_template_conversion(metadata: SessionMetadata, template: Optional[Dict[str, Any]]) -> None:
    st.subheader("Create template from this workspace")
    workspace = Path(metadata.workspace_path)
    if not workspace.exists():
        st.info("Workspace not found.")
        return

    files = filter_visible_files(workspace, limit=500)
    rel_files = [str(path.relative_to(workspace)) for path in files]

    default_name = f"{metadata.name}-template"
    default_label = get_template_label(template) if template else default_name

    with st.form(f"template_from_{metadata.name}"):
        template_name = st.text_input("Template name", value=default_name)
        template_label = st.text_input("Label", value=default_label)
        template_description = st.text_area("Description", value=metadata.description or "")
        template_command = st.text_input("Command", value=metadata.command or "")
        session_type_value = metadata.session_type.value if metadata.session_type else "long_running"
        session_type_choice = st.selectbox(
            "Session type",
            options=["long_running", "one_off"],
            index=0 if session_type_value == "long_running" else 1,
        )
        working_dir = st.text_input("Working directory", value="")
        selected_files = st.multiselect("Include files", options=rel_files)
        submitted = st.form_submit_button("Save template", use_container_width=True)

        if submitted:
            if not template_name.strip():
                st.error("Template name is required.")
            else:
                payload = {
                    "name": template_name.strip(),
                    "label": template_label.strip() or template_name.strip(),
                    "command": template_command.strip() or None,
                    "session_type": session_type_choice,
                    "working_dir": working_dir.strip() or None,
                    "description": template_description.strip() or None,
                    "env": {},
                    "include_files": [],
                }
                include_paths = [workspace / Path(rel) for rel in selected_files]
                try:
                    MANAGER.save_template(payload, include_sources=include_paths)
                    st.success(f"Template '{payload['name']}' saved.")
                except Exception as exc:  # pylint: disable=broad-except
                    st.error(f"Unable to save template: {exc}")


def format_include(entry: Any) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("target") or entry.get("source", "")
    return str(entry)


def collect_assets(root: Path, limit: int) -> List[Path]:
    results: List[Path] = []
    if not root.exists():
        return results
    for path in sorted(root.rglob("*")):
        if len(results) >= limit:
            break
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts):
            results.append(path)
    return results


def render_asset_editor(root: Path, files: List[Path], state_prefix: str) -> None:
    if not files:
        st.info("No assets discovered.")
        return

    page_size = st.selectbox(
        "Assets per page",
        options=[25, 50, 100, 200],
        index=0,
        key=f"{state_prefix}_page_size",
    )

    total_pages = max(1, math.ceil(len(files) / page_size))
    current_page_key = f"{state_prefix}_page"
    state = st.session_state
    current_page_default = state.get(current_page_key, 1)
    current_page = st.number_input(
        "Page",
        min_value=1,
        max_value=total_pages,
        value=min(current_page_default, total_pages),
        step=1,
        key=current_page_key,
    )

    start = (current_page - 1) * page_size
    end = start + page_size
    page_files = files[start:end]

    st.caption(f"Showing assets {start + 1} – {min(end, len(files))} of {len(files)}")

    records = []
    for file in page_files:
        stat = file.stat()
        records.append(
            {
                "Path": str(file.relative_to(root)),
                "Size (bytes)": f"{stat.st_size}",
                "Modified": datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds"),
            }
        )

    st.dataframe(records, use_container_width=True, hide_index=True)

    options = [record["Path"] for record in records]
    if not options:
        st.info("No assets on this page.")
        return

    selection_key = f"{state_prefix}_selection"
    previous_selection = state.get(selection_key)
    if previous_selection in options:
        default_index = options.index(previous_selection)
    else:
        default_index = 0

    selected_rel = st.selectbox(
        "Asset to edit",
        options=options,
        index=default_index,
        key=f"{selection_key}_widget",
    )
    state[selection_key] = selected_rel

    file_path = root / selected_rel

    try:
        content = file_path.read_text(encoding="utf-8")
        binary = False
    except UnicodeDecodeError:
        content = file_path.read_bytes()
        binary = True

    if binary:
        st.warning("Binary assets are read-only in this view.")
        st.download_button("Download asset", data=content, file_name=file_path.name)
        return

    with st.form(f"{state_prefix}_editor"):
        edited = st.text_area("Contents", content, height=400)
        saved = st.form_submit_button("Save asset", use_container_width=True)
        if saved:
            file_path.write_text(edited, encoding="utf-8")
            st.success("Asset saved.")

    st.caption(f"Path: {file_path}")


def render_session_overview(metadata: SessionMetadata, template: Optional[Dict[str, Any]]) -> None:
    if template:
        st.subheader(f"Template: {get_template_label(template)}")
        if template.get("description"):
            st.caption(template["description"])

    st.markdown(f"### Session `{metadata.name}` — {metadata.status}")

    runtime_details = getattr(metadata, "runtime", {}) or {}
    summary_cols = st.columns(3)
    summary_cols[0].markdown(
        "**Active command**\n\n" + (f"`{runtime_details.get('pane_current_command')}`" if runtime_details.get("pane_current_command") else "—")
    )
    summary_cols[1].markdown(
        "**Working directory**\n\n" + (f"`{runtime_details.get('pane_current_path')}`" if runtime_details.get("pane_current_path") else "—")
    )
    summary_cols[2].markdown(
        "**Last activity**\n\n" + format_timestamp(runtime_details.get("client_last_activity"))
    )

    action_cols = st.columns([1, 1, 4])
    if action_cols[0].button("Kill session", key=f"kill_{metadata.name}"):
        try:
            MANAGER.kill_session(metadata.name)
            st.success(f"Session '{metadata.name}' terminated.")
            st.session_state[KEY_ACTIVE_SESSION] = None
            update_query_params()
            st.rerun()
        except Exception as exc:  # pylint: disable=broad-except
            st.error(f"Unable to kill session: {exc}")

    log_path = Path(metadata.log_path)
    if log_path.exists():
        log_bytes = log_path.read_bytes()
        action_cols[1].download_button(
            "Download log",
            data=log_bytes,
            file_name=f"{metadata.name}.log",
            key=f"download_{metadata.name}",
        )

    tmux_clients = runtime_details.get("tmux_clients") or []
    tmux_panes = runtime_details.get("tmux_panes") or []

    if tmux_panes or tmux_clients:
        with st.expander("tmux runtime details", expanded=False):
            if tmux_panes:
                pane_rows = [
                    {
                        "Pane": pane.get("pane_id"),
                        "Index": pane.get("pane_index"),
                        "Active": "yes" if pane.get("active") else "",
                        "Command": pane.get("pane_current_command") or "",
                        "Path": pane.get("pane_current_path") or "",
                    }
                    for pane in tmux_panes
                ]
                st.markdown("**Panes**")
                st.table(pane_rows)
            else:
                st.caption("No pane details reported")

            if tmux_clients:
                client_rows = [
                    {
                        "TTY": client.get("client_tty") or "",
                        "Last activity": format_timestamp(client.get("client_last_activity")),
                        "Size": (
                            f"{client.get('client_width') or '—'}×{client.get('client_height') or '—'}"
                        ),
                    }
                    for client in tmux_clients
                ]
                st.markdown("**Clients**")
                st.table(client_rows)
            else:
                st.caption("No clients attached")

    st.divider()
    st.subheader("Recent log output")
    logs = MANAGER.tail_log(metadata.name, lines=400)
    if logs:
        st.code(logs, language="bash")
    else:
        st.info("No logs yet.")


def render_template_admin(templates: List[Dict[str, Any]]) -> None:
    st.header("Templates administration")

    if st.button("Refresh templates", use_container_width=False):
        MANAGER.refresh_templates()
        st.rerun()

    if not templates:
        st.info("No templates found yet. Use the form below to add one.")
    else:
        st.subheader("Available templates")
        cols = st.columns([2, 2, 2, 2, 2])
        headers = ["Name", "Label", "Type", "Working Dir", "Source"]
        for col, header in zip(cols, headers):
            col.markdown(f"**{header}**")
        for tpl in templates:
            cols[0].write(tpl.get("name"))
            cols[1].write(get_template_label(tpl))
            cols[2].write(tpl.get("default_type"))
            cols[3].write(tpl.get("working_dir") or "(workspace)")
            cols[4].write(tpl.get("source"))

        with st.expander("Template details", expanded=False):
            selected = st.selectbox(
                "Inspect template",
                options=[tpl["name"] for tpl in templates],
                format_func=lambda name: get_template_label(get_template_by_name(templates, name) or {}),
            )
            tpl = get_template_by_name(templates, selected)
            if tpl:
                st.json(tpl, expanded=False)
                include_files = tpl.get("include_files") or []
                if include_files:
                    st.markdown(
                        "**Included files:** "
                        + ", ".join(filter(None, (format_include(entry) for entry in include_files)))
                    )

        st.subheader("Template editor")
        editor_options = [tpl["name"] for tpl in templates]
        editor_choice = st.selectbox(
            "Select template",
            options=editor_options,
            format_func=lambda name: get_template_label(get_template_by_name(templates, name) or {}),
            key="template_editor_choice",
        )
        editor_source = MANAGER.template_sources.get(editor_choice)
        if not editor_source or editor_source == "built-in":
            payload = get_template_by_name(templates, editor_choice)
            if payload:
                st.code(json.dumps(payload, indent=2, sort_keys=True), language="json")
            st.info("Built-in template. Save a custom copy before editing.")
        else:
            template_path = Path(editor_source)
            if not template_path.exists():
                st.error(f"Template file missing: {template_path}")
            else:
                try:
                    existing_text = template_path.read_text(encoding="utf-8")
                except OSError as exc:  # pylint: disable=broad-except
                    st.error(f"Unable to read template: {exc}")
                else:
                    with st.form("template_editor_form"):
                        edited_text = st.text_area("Template JSON", existing_text, height=400)
                        saved = st.form_submit_button("Save template", use_container_width=True)
                        if saved:
                            try:
                                json.loads(edited_text)
                            except json.JSONDecodeError as exc:  # pylint: disable=broad-except
                                st.error(f"Invalid JSON: {exc}")
                            else:
                                try:
                                    template_path.write_text(edited_text, encoding="utf-8")
                                except OSError as exc:  # pylint: disable=broad-except
                                    st.error(f"Unable to save template: {exc}")
                                else:
                                    st.success("Template saved.")
                                    MANAGER.refresh_templates()
                                    st.rerun()

    st.divider()

    st.subheader("Delete template")
    deletable = [
        tpl
        for tpl in templates
        if MANAGER.template_sources.get(tpl["name"]) and MANAGER.template_sources.get(tpl["name"]) != "built-in"
    ]
    with st.form("delete_form"):
        if not deletable:
            st.write("No user templates to delete.")
            st.form_submit_button("Delete", disabled=True)
        else:
            delete_target = st.selectbox("Template", options=[tpl["name"] for tpl in deletable])
            delete_submitted = st.form_submit_button("Delete", use_container_width=True)
            if delete_submitted:
                try:
                    MANAGER.delete_template(delete_target)
                    st.success(f"Template '{delete_target}' deleted.")
                    MANAGER.refresh_templates()
                    st.rerun()
                except Exception as exc:  # pylint: disable=broad-except
                    st.error(f"Unable to delete template: {exc}")

    st.divider()

    st.subheader("Template assets")
    asset_locations: List[tuple[str, Path]] = [
        ("Built-in assets", MANAGER.asset_dir),
        ("User assets", MANAGER.user_asset_dir),
    ]
    location_label = st.selectbox("Asset location", [label for label, _ in asset_locations])
    asset_root = next(path for label, path in asset_locations if label == location_label)

    if not asset_root.exists():
        st.warning(f"Path does not exist: {asset_root}")
        return

    st.write(f"Root: `{asset_root}`")

    scan_limit = st.slider("Scan limit", min_value=100, max_value=2000, value=500, step=100)
    files = collect_assets(asset_root, scan_limit)
    state_prefix = f"assets_{location_label.lower().replace(' ', '_')}"
    render_asset_editor(asset_root, files, state_prefix)


def render_create_session_form(templates: List[Dict[str, Any]], selected_template: Optional[Dict[str, Any]]) -> None:
    if not templates:
        st.warning("Add templates before launching sessions.")
        return

    template_options = [tpl["name"] for tpl in templates]
    default_template_name = selected_template["name"] if selected_template else template_options[0]
    template_key = st.selectbox(
        "Template",
        options=template_options,
        index=template_options.index(default_template_name),
        format_func=lambda key: get_template_label(get_template_by_name(templates, key) or {}),
        key="create_template_choice",
    )
    chosen_template = get_template_by_name(templates, template_key)
    if chosen_template and chosen_template.get("description"):
        st.caption(chosen_template["description"])

    include_files = chosen_template.get("include_files") if chosen_template else []
    pretty: List[str] = []
    for entry in include_files or []:
        pretty.append(format_include(entry))
    if pretty:
        st.caption("Includes: " + ", ".join(filter(None, pretty)))

    suggested_name = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    default_session_name = f"{template_key}-{suggested_name}" if template_key else suggested_name

    session_name = st.text_input("Session name", value=default_session_name)
    custom_command = st.text_input("Command override", placeholder="Leave blank to use the template default")
    description = st.text_area("Description", placeholder="Optional summary of the session")
    create_clicked = st.button("Launch session", use_container_width=True)

    if create_clicked:
        if not session_name.strip():
            st.error("Session name is required.")
            return
        try:
            metadata = MANAGER.create_session(
                session_name.strip(),
                template=template_key,
                command=custom_command.strip() or None,
                description=description.strip() or None,
            )
            st.success(f"Session '{metadata.name}' is ready.")
            state = st.session_state
            state[KEY_ACTIVE_SESSION] = metadata.name
            state[KEY_ACTIVE_TEMPLATE] = metadata.template
            update_query_params()
            st.switch_page("app.py")
        except Exception as exc:  # pylint: disable=broad-except
            st.error(f"Unable to create session: {exc}")
