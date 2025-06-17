import streamlit as st
import os
import time

st.set_page_config(
    page_title="Errors",
    page_icon="🚨",
    layout="wide"
)

# Define the path to ERRORS.md
ERRORS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.vibe', 'ERRORS.md')

def load_errors():
    """Load the content of ERRORS.md"""
    try:
        with open(ERRORS_PATH, 'r') as f:
            return f.read()
    except FileNotFoundError:
        return "# Errors\n\nNo errors file found. Errors from previous development iterations will appear here."
    except Exception as e:
        return f"Error loading errors: {str(e)}"

def save_errors(content):
    """Save content to ERRORS.md"""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(ERRORS_PATH), exist_ok=True)
        with open(ERRORS_PATH, 'w') as f:
            f.write(content)
        return True, "Errors file saved successfully!"
    except Exception as e:
        return False, f"Error saving errors: {str(e)}"

def clear_errors():
    """Clear the errors file"""
    try:
        with open(ERRORS_PATH, 'w') as f:
            f.write("# Errors\n\n<!-- No errors from previous run -->\n")
        return True, "Errors cleared successfully!"
    except Exception as e:
        return False, f"Error clearing errors: {str(e)}"

def main():
    st.title("🚨 Errors")
    st.markdown("View and manage errors from previous development iterations. The AI assistant uses this to track and fix issues.")
    
    # Load current content
    if 'errors_content' not in st.session_state:
        st.session_state.errors_content = load_errors()
    
    # Create a text area for editing
    edited_content = st.text_area(
        "Errors Content",
        value=st.session_state.errors_content,
        height=500,
        help="Edit error logs in Markdown format"
    )
    
    # Create columns for buttons
    col1, col2, col3, col4 = st.columns([1, 1, 1, 7])
    
    with col1:
        if st.button("💾 Save", type="primary"):
            success, message = save_errors(edited_content)
            if success:
                st.session_state.errors_content = edited_content
                st.success(message)
                time.sleep(1)
                st.rerun()
            else:
                st.error(message)
    
    with col2:
        if st.button("🔄 Reload"):
            st.session_state.errors_content = load_errors()
            st.rerun()
    
    with col3:
        if st.button("🗑️ Clear", help="Clear all errors"):
            success, message = clear_errors()
            if success:
                st.session_state.errors_content = load_errors()
                st.success(message)
                time.sleep(1)
                st.rerun()
            else:
                st.error(message)
    
    # Show file path
    with st.expander("📁 File Information"):
        st.code(f"File path: {ERRORS_PATH}")
        st.info("This file is part of the .vibe configuration system used by the AI assistant.")

if __name__ == "__main__":
    main()