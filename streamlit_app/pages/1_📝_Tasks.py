import streamlit as st
import os
import time

st.set_page_config(
    page_title="Tasks",
    page_icon="📝",
    layout="wide"
)

# Define the path to TASKS.md
TASKS_PATH = '/home/vibe/.vibe/TASKS.md'

def load_tasks():
    """Load the content of TASKS.md"""
    try:
        with open(TASKS_PATH, 'r') as f:
            return f.read()
    except FileNotFoundError:
        return "# Tasks\n\nNo tasks file found. Create your first task!"
    except Exception as e:
        return f"Error loading tasks: {str(e)}"

def save_tasks(content):
    """Save content to TASKS.md"""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(TASKS_PATH), exist_ok=True)
        with open(TASKS_PATH, 'w') as f:
            f.write(content)
        return True, "Tasks saved successfully!"
    except Exception as e:
        return False, f"Error saving tasks: {str(e)}"

def main():
    st.title("📝 Tasks")
    st.markdown("Edit your project tasks here. Changes are saved automatically when you click 'Save'.")
    
    # Load current content
    if 'tasks_content' not in st.session_state:
        st.session_state.tasks_content = load_tasks()
    
    # Create a text area for editing
    edited_content = st.text_area(
        "Tasks Content",
        value=st.session_state.tasks_content,
        height=500,
        help="Edit your tasks in Markdown format"
    )
    
    # Create columns for buttons
    col1, col2, col3 = st.columns([1, 1, 8])
    
    with col1:
        if st.button("💾 Save", type="primary"):
            success, message = save_tasks(edited_content)
            if success:
                st.session_state.tasks_content = edited_content
                st.success(message)
                time.sleep(1)
                st.rerun()
            else:
                st.error(message)
    
    with col2:
        if st.button("🔄 Reload"):
            st.session_state.tasks_content = load_tasks()
            st.rerun()
    
    # Show file path
    with st.expander("📁 File Information"):
        st.code(f"File path: {TASKS_PATH}")
        st.info("This file is part of the .vibe configuration system used by the AI assistant.")

if __name__ == "__main__":
    main()