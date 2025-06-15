import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="Edit ERRORS.md",
    page_icon="🚨",
    layout="wide"
)

# Path to the ERRORS.md file
ERRORS_FILE = Path("/workspaces/vibestack/.vibe/ERRORS.md")

def main():
    st.title("🚨 Edit ERRORS.md")
    st.markdown("Edit the errors file that tracks issues from previous development iterations.")
    
    # Check if file exists
    if not ERRORS_FILE.exists():
        st.error(f"File not found: {ERRORS_FILE}")
        return
    
    # Read current content
    try:
        with open(ERRORS_FILE, 'r') as f:
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
            key="errors_editor",
            help="Edit the ERRORS.md file content here. This file tracks errors from previous runs."
        )
    
    with col2:
        st.subheader("Preview")
        st.markdown(new_content)
    
    # Save and Clear buttons
    col_save, col_clear, col_status = st.columns([1, 1, 3])
    with col_save:
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            try:
                with open(ERRORS_FILE, 'w') as f:
                    f.write(new_content)
                st.success("✅ File saved successfully!")
                st.balloons()
            except Exception as e:
                st.error(f"Error saving file: {str(e)}")
    
    with col_clear:
        if st.button("🗑️ Clear Errors", type="secondary", use_container_width=True):
            try:
                # Keep the comment header
                clear_content = "<!-- Errors from the previous run go in this file. Use this, and the chat context to determine what the best next course of action would be. If there are no errors, assume this is the first run, or the previous run (if available) was successful -->"
                with open(ERRORS_FILE, 'w') as f:
                    f.write(clear_content)
                st.success("✅ Errors cleared!")
                st.rerun()
            except Exception as e:
                st.error(f"Error clearing file: {str(e)}")
    
    # Display file info
    st.divider()
    file_stats = ERRORS_FILE.stat()
    st.caption(f"**File path:** {ERRORS_FILE}")
    st.caption(f"**File size:** {file_stats.st_size} bytes")
    st.caption(f"**Last modified:** {Path(ERRORS_FILE).stat().st_mtime}")

if __name__ == "__main__":
    main()