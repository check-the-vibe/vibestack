import streamlit as st
import subprocess
from urllib.parse import quote
from streamlit.components.v1 import iframe, html

st.set_page_config(
    page_title="VibeStack",
    page_icon="🚀",
    layout="wide"
)

# Utilities
def get_tmux_sessions():
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#S"],
            capture_output=True,
            text=True,
            check=True,
        )
        sessions = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        seen = set()
        out = []
        for s in sessions:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out
    except FileNotFoundError:
        return None
    except subprocess.CalledProcessError:
        return []

# Optional: shared height via query param (default 600)
default_height = 600
height_param = st.query_params.get("height", default_height)
try:
    iframe_height = int(height_param)
except Exception:
    iframe_height = default_height

# Minimal styling
st.markdown(
    """
    <style>
      .block-container { max-width: 100%; padding-top: 0.5rem; }
      .session-title { font-weight: 600; margin: 0.25rem 0 0.5rem; }
      iframe[title="streamlit_components.v1.iframe"] { border: 1px solid #ddd; border-radius: 4px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Active tmux Sessions")

# Create new session form
with st.container():
    st.subheader("Create a new session")
    with st.form("create_session_form", clear_on_submit=False):
        col_a, col_b = st.columns([1, 2])
        with col_a:
            new_name = st.text_input("Session name", placeholder="my-session")
        with col_b:
            new_prompt = st.text_input("Prompt (optional)", placeholder="Describe what you want to do")
        submitted = st.form_submit_button("Create and open")
    if submitted:
        if not new_name.strip():
            st.warning("Please enter a session name.")
        else:
            url = f"/?arg={quote(new_name.strip())}"
            if new_prompt.strip():
                url += f"&arg={quote(new_prompt.strip())}"
            # Open in a new tab/window
            html(f"""
                <script>
                  window.open('{url}', '_blank');
                </script>
            """, height=0)
            st.success(f"Opened session: {new_name}")

sessions = get_tmux_sessions()

if sessions is None:
    st.info("tmux is not available in this environment.")
elif not sessions:
    st.write("No active tmux sessions found.")
else:
    # Two-column grid of iframes, each loading /?arg=<SESSION>
    cols = st.columns(2)
    for idx, name in enumerate(sessions):
        with cols[idx % 2]:
            st.markdown(f"<div class='session-title'>🖥️ {name}</div>", unsafe_allow_html=True)
            url = f"/?arg={quote(name)}"
            iframe(src=url, height=iframe_height, scrolling=False)
