import streamlit as st
import os
import time

st.set_page_config(
    page_title="Environment",
    page_icon="🌍",
    layout="wide"
)

# Define the path to ENVIRONMENT.md
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.vibe', 'ENVIRONMENT.md')

def load_environment():
    """Load the content of ENVIRONMENT.md"""
    try:
        with open(ENV_PATH, 'r') as f:
            return f.read()
    except FileNotFoundError:
        return "# Environment Configuration\n\nNo environment file found. Configure your environment here!"
    except Exception as e:
        return f"Error loading environment: {str(e)}"

def save_environment(content):
    """Save content to ENVIRONMENT.md"""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(ENV_PATH), exist_ok=True)
        with open(ENV_PATH, 'w') as f:
            f.write(content)
        return True, "Environment configuration saved successfully!"
    except Exception as e:
        return False, f"Error saving environment: {str(e)}"

def main():
    st.title("🌍 Environment Configuration")
    st.markdown("Edit your environment configuration here. This file describes the development environment and constraints.")
    
    # Load current content
    if 'env_content' not in st.session_state:
        st.session_state.env_content = load_environment()
    
    # Create a text area for editing
    edited_content = st.text_area(
        "Environment Content",
        value=st.session_state.env_content,
        height=500,
        help="Edit your environment configuration in Markdown format"
    )
    
    # Create columns for buttons
    col1, col2, col3 = st.columns([1, 1, 8])
    
    with col1:
        if st.button("💾 Save", type="primary"):
            success, message = save_environment(edited_content)
            if success:
                st.session_state.env_content = edited_content
                st.success(message)
                time.sleep(1)
                st.rerun()
            else:
                st.error(message)
    
    with col2:
        if st.button("🔄 Reload"):
            st.session_state.env_content = load_environment()
            st.rerun()
    
    # Show file path
    with st.expander("📁 File Information"):
        st.code(f"File path: {ENV_PATH}")
        st.info("This file is part of the .vibe configuration system used by the AI assistant.")

if __name__ == "__main__":
    main()