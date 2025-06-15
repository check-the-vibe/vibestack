import streamlit as st
from pathlib import Path
import pandas as pd
import csv
from io import StringIO

st.set_page_config(
    page_title="Edit LINKS.csv",
    page_icon="🔗",
    layout="wide"
)

# Path to the LINKS.csv file
LINKS_FILE = Path("/workspaces/vibestack/.vibe/LINKS.csv")

def main():
    st.title("🔗 Edit LINKS.csv")
    st.markdown("Edit the links file that contains external documentation and resources.")
    
    # Check if file exists
    if not LINKS_FILE.exists():
        st.error(f"File not found: {LINKS_FILE}")
        return
    
    # Read current content
    try:
        df = pd.read_csv(LINKS_FILE)
    except Exception as e:
        st.error(f"Error reading file: {str(e)}")
        return
    
    # Display current links in a table
    st.subheader("Current Links")
    
    # Create an editable dataframe
    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "title": st.column_config.TextColumn(
                "Title",
                help="Title or description of the link",
                width="medium",
                required=True
            ),
            "url": st.column_config.LinkColumn(
                "URL",
                help="The web link",
                width="large",
                required=True
            )
        },
        hide_index=True
    )
    
    # Add new link section
    st.divider()
    st.subheader("Add New Link")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        new_title = st.text_input("Title", placeholder="Enter link title")
    with col2:
        new_url = st.text_input("URL", placeholder="https://example.com")
    
    if st.button("➕ Add Link", type="secondary"):
        if new_title and new_url:
            new_row = pd.DataFrame({"title": [new_title], "url": [new_url]})
            edited_df = pd.concat([edited_df, new_row], ignore_index=True)
            st.success(f"Added link: {new_title}")
            st.rerun()
        else:
            st.error("Please provide both title and URL")
    
    # Save button
    st.divider()
    col_save, col_download, col_status = st.columns([1, 1, 3])
    
    with col_save:
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            try:
                edited_df.to_csv(LINKS_FILE, index=False)
                st.success("✅ File saved successfully!")
                st.balloons()
            except Exception as e:
                st.error(f"Error saving file: {str(e)}")
    
    with col_download:
        # Provide download option
        csv_buffer = StringIO()
        edited_df.to_csv(csv_buffer, index=False)
        csv_str = csv_buffer.getvalue()
        
        st.download_button(
            label="📥 Download CSV",
            data=csv_str,
            file_name="links.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    # Display file info
    st.divider()
    file_stats = LINKS_FILE.stat()
    st.caption(f"**File path:** {LINKS_FILE}")
    st.caption(f"**File size:** {file_stats.st_size} bytes")
    st.caption(f"**Total links:** {len(edited_df)}")

if __name__ == "__main__":
    main()