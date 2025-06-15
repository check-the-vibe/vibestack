import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="Edit ENVIRONMENT.md",
    page_icon="📝",
    layout="wide"
)

# Path to the ENVIRONMENT.md file
ENVIRONMENT_FILE = Path("/workspaces/vibestack/.vibe/ENVIRONMENT.md")

def main():
    st.title("📝 Edit ENVIRONMENT.md")
    st.markdown("Edit the environment configuration file that describes the development container setup.")
    
    # Check if file exists
    if not ENVIRONMENT_FILE.exists():
        st.error(f"File not found: {ENVIRONMENT_FILE}")
        return
    
    # Read current content
    try:
        with open(ENVIRONMENT_FILE, 'r') as f:
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
            key="environment_editor",
            help="Edit the ENVIRONMENT.md file content here"
        )
    
    with col2:
        st.subheader("Preview")
        st.markdown(new_content)
    
    # Save button
    col_save, col_status = st.columns([1, 4])
    with col_save:
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            try:
                with open(ENVIRONMENT_FILE, 'w') as f:
                    f.write(new_content)
                st.success("✅ File saved successfully!")
                st.balloons()
            except Exception as e:
                st.error(f"Error saving file: {str(e)}")
    
    # Display file info
    st.divider()
    file_stats = ENVIRONMENT_FILE.stat()
    st.caption(f"**File path:** {ENVIRONMENT_FILE}")
    st.caption(f"**File size:** {file_stats.st_size} bytes")
    st.caption(f"**Last modified:** {Path(ENVIRONMENT_FILE).stat().st_mtime}")

if __name__ == "__main__":
    main()