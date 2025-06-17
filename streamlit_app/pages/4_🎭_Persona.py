import streamlit as st
import os
import time

st.set_page_config(
    page_title="Persona",
    page_icon="🎭",
    layout="wide"
)

# Define the path to PERSONA.md
PERSONA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.vibe', 'PERSONA.md')

def load_persona():
    """Load the content of PERSONA.md"""
    try:
        with open(PERSONA_PATH, 'r') as f:
            return f.read()
    except FileNotFoundError:
        return "# Persona\n\nNo persona file found. Define the AI assistant's role and behavior here!"
    except Exception as e:
        return f"Error loading persona: {str(e)}"

def save_persona(content):
    """Save content to PERSONA.md"""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(PERSONA_PATH), exist_ok=True)
        with open(PERSONA_PATH, 'w') as f:
            f.write(content)
        return True, "Persona saved successfully!"
    except Exception as e:
        return False, f"Error saving persona: {str(e)}"

def main():
    st.title("🎭 AI Assistant Persona")
    st.markdown("Define how the AI assistant should behave and respond. This shapes the assistant's role and communication style.")
    
    # Load current content
    if 'persona_content' not in st.session_state:
        st.session_state.persona_content = load_persona()
    
    # Create a text area for editing
    edited_content = st.text_area(
        "Persona Content",
        value=st.session_state.persona_content,
        height=500,
        help="Edit the AI persona in Markdown format"
    )
    
    # Create columns for buttons
    col1, col2, col3 = st.columns([1, 1, 8])
    
    with col1:
        if st.button("💾 Save", type="primary"):
            success, message = save_persona(edited_content)
            if success:
                st.session_state.persona_content = edited_content
                st.success(message)
                time.sleep(1)
                st.rerun()
            else:
                st.error(message)
    
    with col2:
        if st.button("🔄 Reload"):
            st.session_state.persona_content = load_persona()
            st.rerun()
    
    # Show file path
    with st.expander("📁 File Information"):
        st.code(f"File path: {PERSONA_PATH}")
        st.info("This file is part of the .vibe configuration system used by the AI assistant.")

if __name__ == "__main__":
    main()