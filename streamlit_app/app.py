import streamlit as st

st.set_page_config(
    page_title="VibeStack",
    page_icon="🚀",
    layout="wide"
)

# Main title with custom styling
st.markdown("""
    <h1 style='text-align: center; color: #4A90E2; font-size: 3em; margin-bottom: 0;'>
        VibeStack
    </h1>
    <p style='text-align: center; font-size: 1.2em; color: #666; margin-top: 0;'>
        Your Development Environment in the Cloud
    </p>
    """, unsafe_allow_html=True)

st.divider()

# Welcome message
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    st.markdown("""
    ### 👋 Hello, Developer!
    
    Welcome to **VibeStack**, your fully-featured development environment accessible from anywhere. 
    Whether you're working on a new project, experimenting with code, or collaborating with AI assistants, 
    VibeStack provides all the tools you need in one place.
    
    ### 🎯 Quick Start
    
    Navigate using the sidebar to access:
    
    - **✏️ Editor** - Edit and manage your project files with syntax highlighting and full file browser
    - **💻 Code** - Access the integrated terminal directly in your browser
    - **📁 File Browser** - Browse and download files from your workspace
    
    ### 🛠️ What's Included
    
    VibeStack comes pre-configured with:
    - Full Linux development environment
    - Python, Node.js, and common development tools
    - AI assistant integration (Claude CLI and LLM tools)
    - Web-based terminal access
    - File editing and management capabilities
    - Git version control
    
    ### 💡 Tips
    
    - Use the **Editor** to modify your `.vibe` configuration files
    - Access the terminal through the **Code** page for command-line operations
    - Your work is automatically saved in the `/home/vibe` directory
    - Check out the interactive command center by typing `vibestack-menu` in any terminal
    
    Ready to start building? Select a page from the sidebar to begin! 🚀
    """)

# Footer
st.markdown("---")
st.markdown("""
    <p style='text-align: center; color: #999; font-size: 0.9em;'>
        VibeStack - Powered by Streamlit, Docker, and Open Source ❤️
    </p>
    """, unsafe_allow_html=True)