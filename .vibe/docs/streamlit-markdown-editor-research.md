# Streamlit Markdown Editor Research

## Overview
Multiple options exist for implementing markdown editing functionality in Streamlit, ranging from simple built-in solutions to advanced third-party components.

## Options for Markdown Editing

### 1. Built-in Solution: st.text_area + st.markdown
The simplest approach using only Streamlit's built-in components.

**Pros:**
- No external dependencies
- Simple to implement
- Lightweight

**Cons:**
- No syntax highlighting
- No rich editing features
- Manual preview/edit switching

**Example:**
```python
import streamlit as st

# Create two columns for editor and preview
col1, col2 = st.columns(2)

with col1:
    st.subheader("Editor")
    content = st.text_area("Edit Markdown", height=400, 
                          value="# Hello\n\nEdit your markdown here...")

with col2:
    st.subheader("Preview")
    st.markdown(content)
```

### 2. streamlit-monaco (VS Code Editor)
Wraps Monaco Editor (VS Code's editor) as a Streamlit component.

**Installation:**
```bash
pip install streamlit-monaco
```

**Pros:**
- Professional code editor experience
- Syntax highlighting for markdown
- Theme support
- IntelliSense capabilities

**Example:**
```python
from streamlit_monaco import st_monaco
import streamlit as st

content = st_monaco(
    value="# Hello world\n\nEdit markdown with syntax highlighting", 
    height="600px", 
    language="markdown",
    theme="vs-dark"
)
st.markdown(content)
```

### 3. streamlit-lexical (Rich Text Editor)
Integrates Meta's Lexical editor for Google Docs-like editing.

**Installation:**
```bash
pip install streamlit-lexical
```

**Pros:**
- Rich text editing experience
- Live markdown rendering
- Modern interface

**Example:**
```python
from streamlit_lexical import st_lexical
import streamlit as st

content = st_lexical(
    value="# Initial content",
    height=400
)
```

### 4. streamlit-code-editor
Built on react-ace with customizable themes and interface.

**Installation:**
```bash
pip install streamlit-code-editor
```

**Pros:**
- Customizable themes
- Multiple language support
- Good for code and markdown

**Example:**
```python
from code_editor import code_editor
import streamlit as st

response = code_editor(
    code="# Markdown content",
    lang="markdown",
    height=20
)

if response['text'] != "":
    st.markdown(response['text'])
```

## Recommendation for VibeStack

For the VibeStack project, I recommend using **st.text_area with st.markdown preview** initially for the following reasons:

1. **No Dependencies**: Keeps the project lightweight
2. **Simple Implementation**: Quick to implement and test
3. **Sufficient for .vibe Files**: The .vibe files are relatively simple markdown/text files
4. **Easy to Upgrade**: Can easily switch to a more advanced solution later if needed

### Implementation Pattern
```python
def create_editor_page(file_path, file_type="markdown"):
    st.title(f"Edit {file_path.name}")
    
    # Read current content
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Create editor with preview
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Editor")
        new_content = st.text_area(
            "Content", 
            value=content, 
            height=500,
            key=f"editor_{file_path.name}"
        )
    
    with col2:
        st.subheader("Preview")
        if file_type == "markdown":
            st.markdown(new_content)
        else:
            st.code(new_content)
    
    # Save button
    if st.button("Save", key=f"save_{file_path.name}"):
        with open(file_path, 'w') as f:
            f.write(new_content)
        st.success("File saved!")
```

This approach provides a functional editor that can be enhanced later if more features are needed.