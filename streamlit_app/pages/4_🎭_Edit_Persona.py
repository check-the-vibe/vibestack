import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="Edit PERSONA.md",
    page_icon="🎭",
    layout="wide"
)

# Path to the PERSONA.md file
PERSONA_FILE = Path("/workspaces/vibestack/.vibe/PERSONA.md")

def main():
    st.title("🎭 Edit PERSONA.md")
    st.markdown("Edit the persona file that defines Claude's role and behavior for this project.")
    
    # Check if file exists
    if not PERSONA_FILE.exists():
        st.error(f"File not found: {PERSONA_FILE}")
        return
    
    # Read current content
    try:
        with open(PERSONA_FILE, 'r') as f:
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
            key="persona_editor",
            help="Edit the PERSONA.md file content here. This defines how Claude should act and respond."
        )
    
    with col2:
        st.subheader("Preview")
        st.markdown(new_content)
    
    # Save button
    col_save, col_status = st.columns([1, 4])
    with col_save:
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            try:
                with open(PERSONA_FILE, 'w') as f:
                    f.write(new_content)
                st.success("✅ File saved successfully!")
                st.balloons()
            except Exception as e:
                st.error(f"Error saving file: {str(e)}")
    
    # Display some tips
    with st.expander("💡 Tips for Writing Effective Personas"):
        st.markdown("""
        - **Be Specific**: Define clear skills and expertise areas
        - **Set Tone**: Describe how Claude should communicate
        - **Define Boundaries**: Specify what Claude should and shouldn't do
        - **Include Context**: Mention relevant project details
        - **Keep it Concise**: Focus on the most important aspects
        """)
    
    # Display file info
    st.divider()
    file_stats = PERSONA_FILE.stat()
    st.caption(f"**File path:** {PERSONA_FILE}")
    st.caption(f"**File size:** {file_stats.st_size} bytes")
    st.caption(f"**Last modified:** {Path(PERSONA_FILE).stat().st_mtime}")

if __name__ == "__main__":
    main()