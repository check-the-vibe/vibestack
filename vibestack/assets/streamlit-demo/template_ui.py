"""Streamlit page bundled with the streamlit-demo template."""
from pathlib import Path

# The Streamlit runtime injects `st`, `session_metadata`, and `session_workspace`.

st.title("Streamlit Template Demo")
st.write(
    "This page ships with the template to prove that Streamlit content "
    "can be packaged and rendered directly inside the VibeStack UI."
)

st.subheader("Session Metadata")
st.json(session_metadata)

st.subheader("Workspace Snapshot")
workspace_path = Path(session_workspace)
items = sorted(p.name for p in workspace_path.iterdir())
st.write(f"Workspace root: `{workspace_path}`")
st.write("Files here when the page loaded:")
st.code("\n".join(items) if items else "(empty workspace)")

with st.expander("Try It Out"):
    name = st.text_input("Add a note", placeholder="Hello from Streamlit")
    if st.button("Submit"):
        st.success(f"Got your note: {name or '(empty)'}")
