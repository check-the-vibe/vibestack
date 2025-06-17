import streamlit as st
import os
from pathlib import Path
import zipfile
import tempfile
import mimetypes
from datetime import datetime

st.set_page_config(page_title="File Viewer", page_icon="📁", layout="wide")

st.title("📁 File Viewer")
st.markdown("Browse and view files in `/home/vibe/.vibe` directory")

BASE_PATH = Path("/home/vibe/.vibe")

def create_zip_download(folder_path):
    """Create a zip file from a folder and return its bytes"""
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    
    with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(folder_path))
                try:
                    zipf.write(file_path, arcname)
                except Exception as e:
                    st.warning(f"Could not add {file}: {e}")
    
    with open(temp_zip.name, 'rb') as f:
        data = f.read()
    
    os.unlink(temp_zip.name)
    return data

def get_file_info(file_path):
    """Get file information"""
    stat = file_path.stat()
    mime_type, _ = mimetypes.guess_type(str(file_path))
    
    return {
        'size': stat.st_size,
        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        'mime_type': mime_type or 'application/octet-stream',
        'is_binary': is_binary_file(file_path)
    }

def is_binary_file(file_path):
    """Check if file is binary"""
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(512)
            if b'\0' in chunk:
                return True
            return False
    except:
        return True

def format_file_size(size):
    """Format file size in human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def display_directory_tree(path, prefix=""):
    """Display directory structure with expandable sections"""
    items = []
    try:
        for item in sorted(path.iterdir()):
            items.append((item, prefix))
    except PermissionError:
        st.error(f"Permission denied: {path}")
        return
    
    for item, prefix in items:
        if item.is_dir():
            col1, col2 = st.columns([4, 1])
            with col1:
                with st.expander(f"📁 {item.name}"):
                    display_directory_tree(item, prefix + "  ")
            with col2:
                if st.download_button(
                    label="⬇️",
                    data=create_zip_download(item),
                    file_name=f"{item.name}.zip",
                    mime="application/zip",
                    key=f"download_folder_{item}",
                    help=f"Download {item.name} as ZIP"
                ):
                    pass
        else:
            if st.button(f"📄 {item.name}", key=str(item)):
                st.session_state.selected_file = str(item)

# File browser sidebar
with st.sidebar:
    st.header("Directory Browser")
    
    if BASE_PATH.exists():
        display_directory_tree(BASE_PATH)
    else:
        st.error(f"Directory {BASE_PATH} does not exist")

# Main content area
if 'selected_file' in st.session_state:
    file_path = Path(st.session_state.selected_file)
    
    st.subheader(f"File: {file_path.name}")
    st.caption(f"Path: {file_path}")
    
    if file_path.exists() and file_path.is_file():
        # Get file info
        file_info = get_file_info(file_path)
        
        # Display file info
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Size", format_file_size(file_info['size']))
        with col2:
            st.metric("Modified", file_info['modified'])
        with col3:
            st.metric("Type", file_info['mime_type'].split('/')[-1] if '/' in file_info['mime_type'] else file_info['mime_type'])
        with col4:
            # Download button for all files
            with open(file_path, 'rb') as f:
                st.download_button(
                    label="⬇️ Download",
                    data=f.read(),
                    file_name=file_path.name,
                    mime=file_info['mime_type'],
                    help="Download this file"
                )
        
        st.markdown("---")
        
        # Check if file is binary
        if file_info['is_binary']:
            st.info("This appears to be a binary file and cannot be displayed as text.")
            st.markdown(f"**File details:**")
            st.markdown(f"- Full path: `{file_path}`")
            st.markdown(f"- MIME type: `{file_info['mime_type']}`")
            st.markdown(f"- Size: {format_file_size(file_info['size'])}")
            st.markdown(f"- Last modified: {file_info['modified']}")
            
            # Show hexdump preview for small binary files
            if file_info['size'] < 1024:  # Less than 1KB
                with st.expander("Hexdump preview (first 256 bytes)"):
                    with open(file_path, 'rb') as f:
                        data = f.read(256)
                        hexdump = ""
                        for i in range(0, len(data), 16):
                            chunk = data[i:i+16]
                            hex_str = ' '.join(f'{b:02x}' for b in chunk)
                            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                            hexdump += f"{i:08x}  {hex_str:<48}  |{ascii_str}|\n"
                        st.code(hexdump, language='text')
        else:
            try:
                # Check file size
                file_size = file_path.stat().st_size
                if file_size > 1_000_000:  # 1MB
                    st.warning(f"Large file ({file_size:,} bytes). Showing first 10,000 characters.")
                    content = file_path.read_text(encoding='utf-8', errors='ignore')[:10000]
                else:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                
                # Display file content based on extension
                if file_path.suffix in ['.md', '.markdown']:
                    st.markdown("### Content (Markdown Rendered)")
                    st.markdown(content)
                    
                    with st.expander("View Raw Content"):
                        st.code(content, language='markdown')
                
                elif file_path.suffix in ['.py', '.js', '.json', '.yaml', '.yml', '.txt', '.sh', '.bash']:
                    lang_map = {
                        '.py': 'python',
                        '.js': 'javascript',
                        '.json': 'json',
                        '.yaml': 'yaml',
                        '.yml': 'yaml',
                        '.sh': 'bash',
                        '.bash': 'bash',
                        '.txt': 'text'
                    }
                    st.code(content, language=lang_map.get(file_path.suffix, 'text'))
                
                elif file_path.suffix in ['.csv']:
                    st.markdown("### CSV Content")
                    import pandas as pd
                    try:
                        df = pd.read_csv(file_path)
                        st.dataframe(df, use_container_width=True)
                    except Exception as e:
                        st.error(f"Error reading CSV: {e}")
                        st.code(content)
                
                else:
                    # Default text display
                    st.text_area("File Content", content, height=400)
                    
            except Exception as e:
                st.error(f"Error reading file: {e}")
    else:
        st.info("Select a file from the sidebar to view its contents")
else:
    st.info("👈 Select a file from the sidebar to view its contents")

# Quick navigation for common files
st.markdown("---")
st.subheader("Quick Links")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("📝 View TASKS.md"):
        st.session_state.selected_file = str(BASE_PATH / "TASKS.md")
        st.rerun()

with col2:
    if st.button("🚨 View ERRORS.md"):
        st.session_state.selected_file = str(BASE_PATH / "ERRORS.md")
        st.rerun()

with col3:
    if st.button("📊 View LOG.txt"):
        st.session_state.selected_file = str(BASE_PATH / "LOG.txt")
        st.rerun()

# Docs folder quick access
if (BASE_PATH / "docs").exists():
    st.subheader("📚 Documentation Files")
    docs_path = BASE_PATH / "docs"
    doc_files = list(docs_path.glob("*"))
    
    if doc_files:
        doc_cols = st.columns(min(3, len(doc_files)))
        for idx, doc_file in enumerate(doc_files[:9]):  # Show max 9 docs
            with doc_cols[idx % 3]:
                if st.button(f"📄 {doc_file.name}", key=f"doc_{doc_file.name}"):
                    st.session_state.selected_file = str(doc_file)
                    st.rerun()
    else:
        st.info("No documentation files found in /home/vibe/.vibe/docs")