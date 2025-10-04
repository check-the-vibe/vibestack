import streamlit as st
from pathlib import Path
import json

st.set_page_config(
    page_title="Chrome Extension",
    page_icon="🧩",
    layout="wide"
)

st.title("🧩 Chrome Extension")

st.markdown("""
The Vibestack Chrome Extension provides a terminal overlay for managing sessions from any webpage.
""")

st.header("📥 Installation")

col1, col2 = st.columns([2, 1])

with col1:
    st.markdown("""
    ### Steps to Install
    
    1. **Download Extension Files**
       - Access at: `/extension/` endpoint
       - Or use the vibestack-extension folder from this repository
    
    2. **Load in Chrome**
       - Navigate to `chrome://extensions/`
       - Enable **Developer mode** (top-right toggle)
       - Click **Load unpacked**
       - Select the `vibestack-extension` directory
    
    3. **Start Using**
       - Press `Ctrl+~` on any webpage
       - Extension auto-detects Vibestack URL
       - Select or create a session
       - Execute commands remotely
    """)

with col2:
    st.info("""
    **Quick Access**
    
    Extension files are served at:
    ```
    /extension/
    ```
    
    Download all files and load as unpacked extension.
    """)

st.header("📋 Extension Information")

extension_path = Path("/home/vibe/vibestack-extension")
manifest_path = extension_path / "manifest.json"

if manifest_path.exists():
    try:
        manifest = json.loads(manifest_path.read_text())
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Name", manifest.get("name", "N/A"))
        with col2:
            st.metric("Version", manifest.get("version", "N/A"))
        with col3:
            st.metric("Manifest", f"v{manifest.get('manifest_version', 'N/A')}")
        
        st.subheader("Permissions")
        permissions = manifest.get("permissions", [])
        host_permissions = manifest.get("host_permissions", [])
        
        st.write("**Required Permissions:**")
        for perm in permissions:
            st.write(f"- `{perm}`")
        
        st.write("**Host Permissions:**")
        for host in host_permissions:
            st.write(f"- `{host}`")
            
    except Exception as e:
        st.error(f"Error reading manifest: {e}")
else:
    st.warning("Extension manifest not found. Ensure extension is copied to Docker image.")

st.header("✨ Features")

features = [
    ("🎹", "Keyboard Shortcut", "Press `Ctrl+~` to toggle terminal overlay"),
    ("🔄", "Auto-Configuration", "Automatically detects Vibestack API URL"),
    ("📡", "Real-time Logs", "1-second polling for session output"),
    ("🎯", "Session Management", "Create, list, and switch sessions"),
    ("⚡", "Command Execution", "Direct command injection to tmux sessions"),
    ("🌐", "Universal Access", "Works on any webpage in Chrome"),
]

cols = st.columns(2)
for idx, (icon, title, desc) in enumerate(features):
    with cols[idx % 2]:
        st.markdown(f"**{icon} {title}**")
        st.write(desc)
        st.divider()

with st.expander("🔧 Troubleshooting"):
    st.markdown("""
    ### Common Issues
    
    **Extension not loading:**
    - Ensure Developer mode is enabled in `chrome://extensions/`
    - Check that all files are present in the directory
    - Look for errors in the extension details page
    
    **Cannot connect to API:**
    - Verify Vibestack URL is correct
    - Check nginx is serving `/admin/api/` correctly
    - Ensure CORS headers are configured
    
    **Terminal overlay not appearing:**
    - Try `Ctrl+~` or `Cmd+~` (Mac)
    - Check browser console for errors
    - Reload the page and try again
    
    **Sessions not updating:**
    - Check session is still active in Vibestack
    - Verify API connectivity
    - Check browser network tab for failed requests
    """)

st.divider()
st.caption("For detailed documentation, see vibestack-extension/README.md")
