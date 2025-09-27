import streamlit as st

from common import (
    KEY_ACTIVE_SESSION,
    filter_active_sessions,
    load_templates,
    list_sessions,
    render_sidebar,
    sync_state_from_query,
)
from onboarding import render_onboarding_gate, render_onboarding_sidebar_controls

st.set_page_config(
    page_title="VibeStack Control Center",
    page_icon="🚀",
    layout="wide",
)

sync_state_from_query()
state = st.session_state

templates = load_templates()
sessions = list_sessions()
render_sidebar(active_page="Home")
render_onboarding_sidebar_controls()

onboarding_active = render_onboarding_gate()

hero_css = """
<style>
    .vibestack-hero {
        border: 2px solid #0ff;
        border-radius: 12px;
        padding: 5rem 2rem;
        text-align: center;
        margin-bottom: 2rem;
        background: radial-gradient(circle at top, rgba(0, 255, 213, 0.15), rgba(0, 0, 0, 0.85));
        box-shadow: 0 0 40px rgba(0, 255, 213, 0.25);
    }

    .vibestack-hero h1 {
        font-family: 'Source Code Pro', 'Courier New', monospace;
        font-size: clamp(3rem, 8vw, 6rem);
        letter-spacing: 0.35rem;
        color: #0ff;
        text-transform: uppercase;
        margin: 0;
        text-shadow: 0 0 20px rgba(0, 255, 213, 0.6);
    }

    .vibestack-hero p {
        color: rgba(255, 255, 255, 0.75);
        font-size: clamp(1rem, 2vw, 1.4rem);
        margin-top: 1.5rem;
        font-family: 'Source Code Pro', 'Courier New', monospace;
    }
</style>
"""

st.markdown(hero_css, unsafe_allow_html=True)

with st.container():
    st.markdown(
        """
        <div class="vibestack-hero">
            <h1>WELCOME TO VIBESTACK</h1>
            <p>Your codex-ready control plane for automated session orchestration.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

if onboarding_active:
    st.info("Complete the onboarding steps above to unlock the Sessions workspace and automation tools.")
else:
    st.success("Onboarding complete. You're ready to launch sessions.")

st.page_link("pages/1_📋_Sessions.py", label="Jump to Sessions", icon="🚀", help="Select or create a workspace")
