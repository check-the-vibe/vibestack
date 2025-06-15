import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="Edit TASKS.md",
    page_icon="✅",
    layout="wide"
)

# Path to the TASKS.md file
TASKS_FILE = Path("/workspaces/vibestack/.vibe/TASKS.md")

def main():
    st.title("✅ Edit TASKS.md")
    st.markdown("Edit the tasks file that tracks what needs to be done and what has been completed.")
    
    # Check if file exists
    if not TASKS_FILE.exists():
        st.error(f"File not found: {TASKS_FILE}")
        return
    
    # Read current content
    try:
        with open(TASKS_FILE, 'r') as f:
            content = f.read()
    except Exception as e:
        st.error(f"Error reading file: {str(e)}")
        return
    
    # Create two columns for editor and preview
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Editor")
        new_content = st.text_area(
            "Content", 
            value=content, 
            height=600,
            key="tasks_editor",
            help="Edit the TASKS.md file content here. Track open and completed tasks."
        )
    
    with col2:
        st.subheader("Preview")
        st.markdown(new_content)
    
    # Save button
    col_save, col_status = st.columns([1, 4])
    with col_save:
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            try:
                with open(TASKS_FILE, 'w') as f:
                    f.write(new_content)
                st.success("✅ File saved successfully!")
                st.balloons()
            except Exception as e:
                st.error(f"Error saving file: {str(e)}")
    
    # Task management tips
    with st.expander("📋 Task Management Tips"):
        st.markdown("""
        ### Suggested Format:
        ```markdown
        # Outcome
        Brief description of the desired outcome
        
        ## Research
        - [ ] Task 1
        - [x] Completed task
        
        ## POC
        - [ ] Proof of concept tasks
        
        ## Development
        - [ ] Development tasks
        
        ## Verification & Documentation
        - [ ] Testing and documentation tasks
        ```
        
        ### Tips:
        - Use `- [ ]` for open tasks
        - Use `- [x]` for completed tasks  
        - Group tasks by category or phase
        - Add dates or priorities as needed
        - Keep descriptions clear and actionable
        """)
    
    # Display file info
    st.divider()
    file_stats = TASKS_FILE.stat()
    st.caption(f"**File path:** {TASKS_FILE}")
    st.caption(f"**File size:** {file_stats.st_size} bytes")
    st.caption(f"**Last modified:** {Path(TASKS_FILE).stat().st_mtime}")

if __name__ == "__main__":
    main()