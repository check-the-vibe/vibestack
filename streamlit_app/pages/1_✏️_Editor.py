import streamlit as st
import os
import zipfile
import tempfile
import mimetypes
import binascii
from datetime import datetime
from pathlib import Path

st.set_page_config(
    page_title="Editor",
    page_icon="✏️",
    layout="wide"
)

st.title("✏️ Editor")
st.write("Edit and manage files in the .vibe directory")

BASE_DIR = "/home/vibe/.vibe"

# Ensure the .vibe directory exists
os.makedirs(BASE_DIR, exist_ok=True)

# Utility functions
def format_file_size(size_bytes):
    """Format file size in human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

def get_file_info(filepath):
    """Get file metadata"""
    try:
        stat = os.stat(filepath)
        mime_type, _ = mimetypes.guess_type(filepath)
        return {
            'size': stat.st_size,
            'size_formatted': format_file_size(stat.st_size),
            'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            'mime_type': mime_type or 'application/octet-stream'
        }
    except:
        return None

def is_binary_file(filepath):
    """Check if file is binary"""
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(1024)
            if b'\0' in chunk:
                return True
            # Check for high ratio of non-text characters
            text_chars = set(bytes(range(32, 127)) + b'\n\r\t\b')
            non_text = sum(1 for byte in chunk if byte not in text_chars)
            return non_text / len(chunk) > 0.3 if chunk else False
    except:
        return True

def create_directory_tree(path, prefix="", is_last=True):
    """Create a tree structure of directories and files"""
    items = []
    base_name = os.path.basename(path) or path
    
    # Create current item
    connector = "└── " if is_last else "├── "
    items.append({
        'display': prefix + connector + base_name,
        'path': path,
        'is_dir': os.path.isdir(path),
        'name': base_name
    })
    
    # If it's a directory, add children
    if os.path.isdir(path):
        try:
            children = sorted(os.listdir(path))
            # Filter out hidden files starting with .
            children = [c for c in children if not c.startswith('.')]
            
            # Separate directories and files
            dirs = [c for c in children if os.path.isdir(os.path.join(path, c))]
            files = [c for c in children if not os.path.isdir(os.path.join(path, c))]
            
            # Sort dirs and files separately
            all_children = sorted(dirs) + sorted(files)
            
            for i, child in enumerate(all_children):
                child_path = os.path.join(path, child)
                extension = "    " if is_last else "│   "
                child_items = create_directory_tree(
                    child_path, 
                    prefix + extension, 
                    i == len(all_children) - 1
                )
                items.extend(child_items)
        except PermissionError:
            pass
    
    return items

def create_zip_download(folder_path):
    """Create a zip file from a folder"""
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    
    with zipfile.ZipFile(temp_file.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for file in files:
                if not file.startswith('.'):
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, os.path.dirname(folder_path))
                    zipf.write(file_path, arcname)
    
    temp_file.close()
    
    with open(temp_file.name, 'rb') as f:
        data = f.read()
    
    os.unlink(temp_file.name)
    return data

# Main UI
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("📂 File Browser")
    
    # Quick access buttons for common files
    st.write("**Quick Access:**")
    quick_files = [
        ("📝 TASKS.md", os.path.join(BASE_DIR, "TASKS.md")),
        ("🚨 ERRORS.md", os.path.join(BASE_DIR, "ERRORS.md")),
        ("📋 LOG.txt", os.path.join(BASE_DIR, "LOG.txt")),
        ("🌍 ENVIRONMENT.md", os.path.join(BASE_DIR, "ENVIRONMENT.md")),
        ("🎭 PERSONA.md", os.path.join(BASE_DIR, "PERSONA.md")),
    ]
    
    for label, filepath in quick_files:
        if st.button(label, key=f"quick_{os.path.basename(filepath)}"):
            st.session_state.selected_file = filepath
    
    st.divider()
    
    # Directory tree
    st.write("**All Files:**")
    tree_items = create_directory_tree(BASE_DIR)
    
    # Display tree with selection
    for item in tree_items[1:]:  # Skip the root item
        if item['is_dir']:
            st.write(f"📁 {item['display']}")
        else:
            if st.button(item['display'], key=f"tree_{item['path']}"):
                st.session_state.selected_file = item['path']

with col2:
    if 'selected_file' in st.session_state and st.session_state.selected_file:
        filepath = st.session_state.selected_file
        
        if os.path.exists(filepath):
            st.subheader(f"Editing: {os.path.basename(filepath)}")
            
            # Show file info
            file_info = get_file_info(filepath)
            if file_info:
                info_col1, info_col2, info_col3 = st.columns(3)
                with info_col1:
                    st.caption(f"Size: {file_info['size_formatted']}")
                with info_col2:
                    st.caption(f"Modified: {file_info['modified']}")
                with info_col3:
                    st.caption(f"Type: {file_info['mime_type']}")
            
            # Check if file is binary
            if is_binary_file(filepath):
                st.warning("This is a binary file and cannot be edited as text.")
                
                # Show hexdump for small binary files
                if file_info and file_info['size'] < 1024:  # Only for files < 1KB
                    st.write("**Hexdump preview:**")
                    try:
                        with open(filepath, 'rb') as f:
                            data = f.read()
                        hexdump = binascii.hexlify(data).decode('ascii')
                        # Format hexdump in rows of 32 characters
                        formatted_hex = '\n'.join([hexdump[i:i+32] for i in range(0, len(hexdump), 32)])
                        st.code(formatted_hex, language='text')
                    except Exception as e:
                        st.error(f"Error reading file: {str(e)}")
                
                # Download button for binary files
                try:
                    with open(filepath, 'rb') as f:
                        file_data = f.read()
                    st.download_button(
                        label="📥 Download File",
                        data=file_data,
                        file_name=os.path.basename(filepath),
                        mime=file_info['mime_type'] if file_info else 'application/octet-stream'
                    )
                except Exception as e:
                    st.error(f"Error preparing download: {str(e)}")
            
            else:
                # Text file - provide editing interface
                
                # Initialize session state for this file
                file_key = f"content_{filepath}"
                
                if file_key not in st.session_state:
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            st.session_state[file_key] = f.read()
                    except Exception as e:
                        st.error(f"Error reading file: {str(e)}")
                        st.session_state[file_key] = ""
                
                # Text editor
                content = st.text_area(
                    "File Content",
                    value=st.session_state[file_key],
                    height=400,
                    key=f"editor_{filepath}"
                )
                
                # Update session state
                st.session_state[file_key] = content
                
                # Action buttons
                button_col1, button_col2, button_col3, button_col4 = st.columns(4)
                
                with button_col1:
                    if st.button("💾 Save", key=f"save_{filepath}"):
                        try:
                            # Ensure directory exists
                            os.makedirs(os.path.dirname(filepath), exist_ok=True)
                            
                            with open(filepath, 'w', encoding='utf-8') as f:
                                f.write(st.session_state[file_key])
                            st.success("File saved successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error saving file: {str(e)}")
                
                with button_col2:
                    if st.button("🔄 Reload", key=f"reload_{filepath}"):
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                st.session_state[file_key] = f.read()
                            st.success("File reloaded successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error reloading file: {str(e)}")
                
                with button_col3:
                    # Special clear button for ERRORS.md
                    if os.path.basename(filepath) == "ERRORS.md":
                        if st.button("🗑️ Clear", key=f"clear_{filepath}"):
                            default_content = "<!-- Errors from the previous run go in this file. Use this, and the chat context to determine what the best next course of action would be. If there are no errors, assume this is the first run, or the previous run (if available) was successful -->"
                            st.session_state[file_key] = default_content
                            try:
                                with open(filepath, 'w', encoding='utf-8') as f:
                                    f.write(default_content)
                                st.success("Errors cleared!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error clearing file: {str(e)}")
                
                with button_col4:
                    # Download button for text files
                    st.download_button(
                        label="📥 Download",
                        data=st.session_state[file_key],
                        file_name=os.path.basename(filepath),
                        mime='text/plain'
                    )
                
                # Show file path info
                with st.expander("📍 File Path Information"):
                    st.code(filepath)
        else:
            st.error(f"File not found: {filepath}")
    else:
        st.info("👈 Select a file from the browser to start editing")
        st.write("You can:")
        st.write("- Click on any file in the file browser to edit it")
        st.write("- Use the quick access buttons for common files")
        st.write("- Download files (binary files can only be downloaded)")
        st.write("- Edit text files directly in the browser")