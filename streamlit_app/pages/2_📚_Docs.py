from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import streamlit as st

from common import render_sidebar, sync_state_from_query
from onboarding import render_onboarding_sidebar_controls

DOC_SOURCES: Tuple[Tuple[str, str], ...] = (
    (".docs", "Internal Guides"),
    ("docs", "Product Docs"),
)
SELECTED_DOC_STATE_KEY = "documentation_viewer_selected_doc"
FILTER_STATE_KEY = "documentation_viewer_filter"


def get_repo_root() -> Path:
    # Page files live in streamlit_app/pages;
    # walk up to the repository root.
    return Path(__file__).resolve().parents[2]


def collect_documents() -> List[Dict[str, object]]:
    repo_root = get_repo_root()
    sources: List[Dict[str, object]] = []
    for relative_directory, label in DOC_SOURCES:
        source_path = repo_root / relative_directory
        if not source_path.exists():
            continue
        markdown_files = sorted(source_path.rglob("*.md"))
        if not markdown_files:
            continue
        sources.append(
            {
                "label": label,
                "root": source_path,
                "files": markdown_files,
            }
        )
    return sources


def build_tree_representation(label: str, relative_paths: List[Path]) -> str:
    tree: Dict[str, object] = {}
    for rel_path in relative_paths:
        parts = rel_path.parts
        cursor: Dict[str, object] = tree
        for directory in parts[:-1]:
            cursor = cursor.setdefault(directory, {})  # type: ignore[assignment]
        cursor[parts[-1]] = None  # type: ignore[index]

    lines: List[str] = [f"{label}/"]

    def render_branch(branch: Dict[str, object], prefix: str) -> None:
        entries = sorted(branch.items(), key=lambda item: (item[1] is None, item[0].lower()))
        for index, (name, child) in enumerate(entries):
            has_children = isinstance(child, dict)
            connector = "└── " if index == len(entries) - 1 else "├── "
            suffix = "/" if has_children else ""
            lines.append(f"{prefix}{connector}{name}{suffix}")
            if has_children:
                extension = "    " if index == len(entries) - 1 else "│   "
                render_branch(child, prefix + extension)  # type: ignore[arg-type]

    render_branch(tree, "")
    return "\n".join(lines)


def render_sidebar_navigation() -> None:
    render_sidebar(active_page="Docs")


st.set_page_config(page_title="Documentation", page_icon="📚", layout="wide")

sync_state_from_query()
render_sidebar_navigation()
render_onboarding_sidebar_controls()

st.title("📚 VibeStack Documentation")

sources = collect_documents()
if not sources:
    st.info("No documentation sources were found. Add Markdown files under `.docs/` or `docs/`.")
    st.stop()

available_documents: List[Tuple[str, str, Path, Path]] = []
for source in sources:
    label = source["label"]  # type: ignore[assignment]
    root: Path = source["root"]  # type: ignore[assignment]
    files: List[Path] = source["files"]  # type: ignore[assignment]
    relative_paths = [path.relative_to(root) for path in files]
    tree_summary = build_tree_representation(label, relative_paths)

    with st.expander(f"{label} ({root.relative_to(get_repo_root())})", expanded=True):
        st.code(tree_summary, language="text")

    for file_path in files:
        display_name = f"{label} · {file_path.relative_to(root).as_posix()}"
        available_documents.append((display_name, label, root, file_path))

filter_default = st.session_state.get(FILTER_STATE_KEY, "")
filter_value = st.text_input("Filter documents", value=str(filter_default), placeholder="Type to filter by name")
st.session_state[FILTER_STATE_KEY] = filter_value

filtered_documents = [entry for entry in available_documents if filter_value.lower() in entry[0].lower()]

if not filtered_documents:
    st.warning("No documents match that filter.")
    st.stop()

selected_default = st.session_state.get(SELECTED_DOC_STATE_KEY)
if selected_default not in {entry[3] for entry in filtered_documents}:  # type: ignore[arg-type]
    selected_default = filtered_documents[0][3]

selected_index = next(
    (index for index, entry in enumerate(filtered_documents) if entry[3] == selected_default),
    0,
)

options = [entry[3] for entry in filtered_documents]
labels = {entry[3]: entry[0] for entry in filtered_documents}

selected_path = st.selectbox(
    "Select a document",
    options,
    index=selected_index,
    format_func=lambda value: labels.get(value, value.name),
)

st.session_state[SELECTED_DOC_STATE_KEY] = selected_path

selected_label = labels[selected_path]
relative_root = selected_path.relative_to(get_repo_root())
content = selected_path.read_text(encoding="utf-8")
modified = datetime.fromtimestamp(selected_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

st.markdown(f"### {selected_label}")
st.caption(f"Source: `{relative_root}` · Last updated: {modified}")
st.markdown(content)
