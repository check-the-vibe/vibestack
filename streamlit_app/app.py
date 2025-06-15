import streamlit as st
import os
from pathlib import Path

st.set_page_config(
    page_title="VibeStack Control Panel",
    page_icon="🎛️",
    layout="wide"
)

def main():
    st.title("🎛️ VibeStack Control Panel")
    st.markdown("Welcome to the VibeStack development environment control panel.")
    
    # Overview section
    st.header("🚀 Quick Start")
    col1, col2 = st.columns(2)
    
    with col1:
        st.info("""
        ### Edit Configuration Files
        Navigate to the pages in the sidebar to edit:
        - 📝 **ENVIRONMENT.md** - Container setup
        - 🚨 **ERRORS.md** - Track errors
        - 🔗 **LINKS.csv** - External resources
        - 🎭 **PERSONA.md** - Claude's behavior
        - ✅ **TASKS.md** - Project tasks
        """)
    
    with col2:
        st.success("""
        ### Run Claude Code
        - 🤖 Go to **Claude Code** page
        - Configure your session prompt
        - Start a session to work on tasks
        - View real-time output
        - Export session logs
        """)
    
    st.divider()
    st.header("📁 File Manager")
    
    # Create tabs for different functions
    tab1, tab2 = st.tabs(["📥 Downloads", "📤 Upload"])
    
    with tab1:
        st.header("Available Files for Download")
        
        # Path to uploads/downloads directory
        downloads_dir = Path("/home/vibe/mnt/")
        
        if not downloads_dir.exists():
            st.warning("Downloads directory not found.")
            return
        
        # Get list of files in the directory
        files = list(downloads_dir.iterdir())
        files = [f for f in files if f.is_file()]
        
        if not files:
            st.info("No files available for download.")
        else:
            st.write(f"Found {len(files)} file(s):")
            
            # Display files with download links
            for file_path in sorted(files):
                col1, col2, col3 = st.columns([3, 1, 1])
                
                with col1:
                    st.write(f"📄 {file_path.name}")
                
                with col2:
                    file_size = file_path.stat().st_size
                    if file_size < 1024:
                        size_str = f"{file_size} B"
                    elif file_size < 1024 * 1024:
                        size_str = f"{file_size / 1024:.1f} KB"
                    else:
                        size_str = f"{file_size / (1024 * 1024):.1f} MB"
                    st.write(size_str)
                
                with col3:
                    with open(file_path, "rb") as file:
                        btn = st.download_button(
                            label="Download",
                            data=file,
                            file_name=file_path.name,
                            key=f"download_{file_path.name}"
                        )
    
    with tab2:
        st.header("Upload Files")
        
        uploaded_files = st.file_uploader(
            "Choose files to upload",
            accept_multiple_files=True,
            help="Upload files to the downloads directory"
        )
        
        if uploaded_files:
            downloads_dir = Path("/home/vibe/mnt/")
            downloads_dir.mkdir(exist_ok=True)
            
            for uploaded_file in uploaded_files:
                # Save the uploaded file
                file_path = downloads_dir / uploaded_file.name
                
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                st.success(f"✅ Uploaded: {uploaded_file.name}")
            
            st.info("Files uploaded successfully! Switch to the Downloads tab to see them.")

if __name__ == "__main__":
    main()