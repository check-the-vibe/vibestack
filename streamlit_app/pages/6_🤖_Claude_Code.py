import streamlit as st
from pathlib import Path
import sys
import subprocess
import json
from datetime import datetime
import logging
import os
import time

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Claude Code Session",
    page_icon="🤖",
    layout="wide"
)

# Session state initialization
if "claude_messages" not in st.session_state:
    st.session_state.claude_messages = []
if "claude_session_active" not in st.session_state:
    st.session_state.claude_session_active = False
if "current_message_index" not in st.session_state:
    st.session_state.current_message_index = 0
if "api_key" not in st.session_state:
    st.session_state.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

def check_claude_cli():
    """Check if Claude Code CLI is installed"""
    try:
        result = subprocess.run(["which", "claude"], capture_output=True, text=True)
        return result.returncode == 0
    except:
        return False

def install_claude_cli():
    """Install Claude Code CLI"""
    with st.spinner("Installing Claude Code CLI..."):
        try:
            # Install claude-code SDK
            subprocess.run([sys.executable, "-m", "pip", "install", "claude-code-sdk"], check=True)
            
            # Install Claude CLI
            subprocess.run(["npm", "install", "-g", "@anthropic-ai/claude-code"], check=True)
            
            st.success("✅ Claude Code CLI installed successfully!")
            return True
        except Exception as e:
            st.error(f"Failed to install Claude Code CLI: {str(e)}")
            return False

def run_claude_cli_directly(prompt, max_turns, api_key):
    """Run Claude CLI directly using subprocess for better compatibility"""
    logger.info(f"Running Claude CLI with prompt: {prompt[:50]}...")
    
    # Build command
    cmd = [
        "claude",
        "--no-color",
        "--max-turns", str(max_turns),
        "--permission-mode", "acceptEdits",
        "--cwd", "/workspaces/vibestack",
        "--allowed-tools", "Read,Write,Edit,Bash,TodoRead,TodoWrite",
        prompt
    ]
    
    # Set up environment with API key
    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = api_key
    
    try:
        # Run the command
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=env
        )
        
        # Container for live updates
        output_container = st.container()
        current_role = None
        current_content = []
        assistant_placeholder = None
        
        # Read output line by line
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            
            logger.debug(f"CLI output: {line}")
            
            # Simple parsing of Claude output
            if line.startswith("Human:") or line.startswith("## Human"):
                # Save previous message if any
                if current_role and current_content:
                    msg = {
                        "role": current_role,
                        "content": "\n".join(current_content),
                        "timestamp": datetime.now().isoformat()
                    }
                    st.session_state.claude_messages.append(msg)
                
                current_role = "user"
                current_content = [line.replace("Human:", "").replace("## Human", "").strip()]
                
                # Display user message
                with output_container:
                    with st.chat_message("user"):
                        st.write(current_content[0])
                        
            elif line.startswith("Assistant:") or line.startswith("## Assistant"):
                # Save previous message if any
                if current_role and current_content:
                    msg = {
                        "role": current_role,
                        "content": "\n".join(current_content),
                        "timestamp": datetime.now().isoformat()
                    }
                    st.session_state.claude_messages.append(msg)
                
                current_role = "assistant"
                current_content = []
                
                # Start assistant message container
                with output_container:
                    with st.chat_message("assistant"):
                        assistant_placeholder = st.empty()
                        
            elif current_role == "assistant" and assistant_placeholder:
                # Accumulate assistant content
                current_content.append(line)
                # Update display with streaming effect
                assistant_placeholder.markdown("\n".join(current_content))
            
            elif current_role == "user" and line:
                current_content.append(line)
        
        # Save final message
        if current_role and current_content:
            msg = {
                "role": current_role,
                "content": "\n".join(current_content),
                "timestamp": datetime.now().isoformat()
            }
            st.session_state.claude_messages.append(msg)
        
        # Wait for process to complete
        process.wait()
        
        if process.returncode == 0:
            st.success("✅ Claude session completed successfully!")
        else:
            stderr = process.stderr.read()
            if "ANTHROPIC_API_KEY" in stderr:
                st.error("❌ Invalid or missing API key. Please check your API key and try again.")
            else:
                st.error(f"Claude session failed with error: {stderr}")
            
    except Exception as e:
        logger.error(f"Error running Claude CLI: {str(e)}")
        st.error(f"Error running Claude CLI: {str(e)}")
    finally:
        st.session_state.claude_session_active = False

def main():
    st.title("🤖 Claude Code Session")
    st.markdown("Start and manage Claude Code sessions to work on your tasks.")
    
    # Check prerequisites
    if not check_claude_cli():
        st.warning("⚠️ Claude Code CLI is not installed.")
        if st.button("Install Claude Code CLI"):
            if install_claude_cli():
                st.rerun()
        st.stop()
    
    # API Key handling
    with st.expander("🔑 API Key Configuration", expanded=not st.session_state.api_key):
        col1, col2 = st.columns([4, 1])
        
        with col1:
            if st.session_state.api_key:
                st.info("✅ API key is configured")
                if st.checkbox("Show/Edit API Key"):
                    new_key = st.text_input(
                        "Anthropic API Key",
                        value=st.session_state.api_key,
                        type="password",
                        help="Your Anthropic API key (starts with 'sk-ant-')"
                    )
                    if new_key != st.session_state.api_key:
                        st.session_state.api_key = new_key
            else:
                st.warning("⚠️ No API key found in environment")
                new_key = st.text_input(
                    "Enter your Anthropic API Key",
                    type="password",
                    placeholder="sk-ant-...",
                    help="Your Anthropic API key (starts with 'sk-ant-')"
                )
                if new_key:
                    st.session_state.api_key = new_key
                    st.rerun()
        
        with col2:
            if st.button("Clear Key", use_container_width=True):
                st.session_state.api_key = ""
                st.rerun()
        
        st.caption("💡 Your API key is stored only for this session and is not saved permanently.")
    
    # Check if API key is available
    if not st.session_state.api_key:
        st.error("❌ Please provide an Anthropic API key to continue.")
        st.info("Get your API key from [console.anthropic.com](https://console.anthropic.com/)")
        st.stop()
    
    # Session configuration
    col1, col2 = st.columns([3, 1])
    
    with col1:
        default_prompt = "Complete all TASKS, resolve any ERRORS"
        prompt = st.text_area(
            "Session Prompt",
            value=default_prompt,
            height=100,
            help="Enter the prompt for Claude to execute"
        )
    
    with col2:
        max_turns = st.number_input(
            "Max Turns",
            min_value=1,
            max_value=50,
            value=10,
            help="Maximum number of interactions"
        )
    
    # Session controls
    col_start, col_stop, col_clear = st.columns([1, 1, 1])
    
    with col_start:
        if st.button(
            "🚀 Start Session", 
            type="primary",
            disabled=st.session_state.claude_session_active,
            use_container_width=True
        ):
            st.session_state.claude_messages = []
            st.session_state.claude_session_active = True
            st.session_state.current_message_index = 0
            st.rerun()
    
    with col_stop:
        if st.button(
            "🛑 Stop Session",
            type="secondary",
            disabled=not st.session_state.claude_session_active,
            use_container_width=True
        ):
            st.session_state.claude_session_active = False
            st.warning("Session stop requested (may take a moment to complete)")
    
    with col_clear:
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.claude_messages = []
            st.session_state.claude_session_active = False
            st.session_state.current_message_index = 0
            logger.info("Chat cleared")
            st.rerun()
    
    # Display session status
    if st.session_state.claude_session_active:
        st.info("🔄 Claude session is running...")
    
    # Chat interface
    st.divider()
    st.subheader("Session Output")
    
    # Display existing messages
    if st.session_state.claude_messages:
        for message in st.session_state.claude_messages[:st.session_state.current_message_index]:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if message.get("timestamp"):
                    st.caption(f"_{message['timestamp']}_")
    
    # Run active session
    if st.session_state.claude_session_active:
        logger.info("Starting Claude CLI session...")
        run_claude_cli_directly(prompt, max_turns, st.session_state.api_key)
        st.rerun()
    
    # Display placeholder if no messages
    if not st.session_state.claude_messages:
        st.info("No messages yet. Start a session to see Claude's output.")
    
    # Export options
    if st.session_state.claude_messages:
        st.divider()
        col_export1, col_export2 = st.columns(2)
        
        with col_export1:
            messages_json = json.dumps(st.session_state.claude_messages, indent=2)
            st.download_button(
                "📥 Export as JSON",
                data=messages_json,
                file_name=f"claude_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True
            )
        
        with col_export2:
            markdown_content = "# Claude Code Session\n\n"
            for msg in st.session_state.claude_messages:
                markdown_content += f"## {msg['role'].title()}\n"
                if msg.get("timestamp"):
                    markdown_content += f"_{msg['timestamp']}_\n\n"
                markdown_content += f"{msg['content']}\n\n---\n\n"
            
            st.download_button(
                "📥 Export as Markdown",
                data=markdown_content,
                file_name=f"claude_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown",
                use_container_width=True
            )

if __name__ == "__main__":
    main()