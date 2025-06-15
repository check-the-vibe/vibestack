# Claude Code Python SDK Research

## Overview
The Claude Code Python SDK provides a programmatic interface to interact with Claude Code, enabling developers to build AI-powered coding assistants and tools.

## Installation
```bash
pip install claude-code-sdk
```

## Prerequisites
- Python 3.10+
- Node.js
- Claude Code CLI: `npm install -g @anthropic-ai/claude-code`

## Basic Usage

### Simple Query Example
```python
import anyio
from claude_code_sdk import query, ClaudeCodeOptions, Message

async def main():
    messages: list[Message] = []
    
    async for message in query(
        prompt="Write a haiku about foo.py",
        options=ClaudeCodeOptions(max_turns=3)
    ):
        messages.append(message)
    
    print(messages)

anyio.run(main)
```

## Key Components

### ClaudeCodeOptions
Configuration options for Claude Code sessions:
- `max_turns` - Maximum number of interactions
- `system_prompt` - Custom system prompt for Claude
- `cwd` - Current working directory for operations
- `allowed_tools` - List of tools Claude can use (e.g., "Read", "Write", "Bash")
- `permission_mode` - Permission handling mode (e.g., "acceptEdits")

### Advanced Configuration
```python
from pathlib import Path

options = ClaudeCodeOptions(
    max_turns=3,
    system_prompt="You are a helpful assistant",
    cwd=Path("/path/to/project"),
    allowed_tools=["Read", "Write", "Bash"],
    permission_mode="acceptEdits"
)
```

## Key Features for Streamlit Integration
1. **Async/Await Support**: Perfect for real-time streaming in Streamlit
2. **Message Streaming**: Can receive messages as they're generated
3. **Session Management**: Each query creates a new session
4. **Tool Control**: Can limit which tools Claude has access to

## Implementation Considerations
1. The SDK uses async/await, so we'll need to handle this in Streamlit
2. Messages are streamed, allowing real-time updates in the chat UI
3. Session persistence might need custom implementation
4. Error handling for API failures should be implemented