import streamlit as st
from streamlit.components.v1 import iframe

st.set_page_config(
    page_title="VibeStack",
    page_icon="🚀",
    layout="wide"
)

def main():
    st.title("🚀 VibeStack")
    
    # Welcome message
    st.markdown("""
    Welcome to VibeStack! This is your development environment control center.
    
    ### 🎯 Quick Navigation
    Use the sidebar to access:
    - **📝 Tasks** - Manage your project tasks
    - **🌍 Environment** - Configure your development environment
    - **🚨 Errors** - Track and resolve errors
    - **🎭 Persona** - Define AI assistant behavior
    
    ### 💻 Terminal
    The terminal below provides direct access to your development environment:
    """)
    
    # Build terminal URL - use relative path to inherit protocol
    # Note: nginx config has /terminal/ with trailing slash
    terminal_url = "/"
    
    # Add custom CSS for full-height iframe
    st.markdown("""
        <style>
        /* Make the main content area use full height */
        .main > div {
            padding-top: 2rem;
            padding-bottom: 0;
        }
        
        /* Style the iframe container */
        iframe[title="streamlit_components.v1.iframe"] {
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        
        /* Remove default Streamlit padding for full width */
        .block-container {
            padding-top: 1rem;
            padding-bottom: 0;
            max-width: 100%;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # Create a container for the terminal
    terminal_container = st.container()
    
    with terminal_container:
        # Calculate dynamic height
        # Default to 80% of typical viewport height
        default_height = 600
        
        # Allow height customization via query params
        height = st.query_params.get("height", default_height)
        
        try:
            height = int(height)
        except:
            height = default_height
        
        # Embed the terminal iframe
        iframe(
            src=terminal_url,
            height=height,
            scrolling=False  # Terminal handles its own scrolling
        )
    
    # Add controls in sidebar
    with st.sidebar:
        st.header("⚙️ Terminal Settings")
        
        # Add info about the pages
        with st.expander("📚 About VibeStack Pages"):
            st.markdown("""
            **Configuration Pages:**
            - **Tasks**: Define and track project objectives
            - **Environment**: Set up your dev environment
            - **Errors**: Monitor and fix issues
            - **Persona**: Customize AI assistant behavior
            
            All changes are saved directly to `.vibe/` files.
            """)
        
        # Height slider
        custom_height = st.slider(
            "Terminal Height (px)",
            min_value=300,
            max_value=1200,
            value=height,
            step=50,
            help="Adjust the terminal height"
        )
        
        # Apply button
        if st.button("Apply Height"):
            st.query_params["height"] = str(custom_height)
            st.rerun()
        
        st.divider()
        
        # Quick size presets
        st.subheader("Quick Sizes")
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📱 Small", use_container_width=True):
                st.query_params["height"] = "400"
                st.rerun()
            
            if st.button("💻 Medium", use_container_width=True):
                st.query_params["height"] = "600"
                st.rerun()
        
        with col2:
            if st.button("🖥️ Large", use_container_width=True):
                st.query_params["height"] = "800"
                st.rerun()
            
            if st.button("📺 Full", use_container_width=True):
                st.query_params["height"] = "1000"
                st.rerun()

if __name__ == "__main__":
    main()