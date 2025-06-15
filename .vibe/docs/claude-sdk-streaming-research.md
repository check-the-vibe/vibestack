# Claude Code Python SDK Streaming Research

## Overview
The Claude Code Python SDK (version 0.0.10) provides an async streaming interface for interacting with the Claude Code CLI. The SDK uses a subprocess transport mechanism to communicate with the CLI and yields messages as they are received.

## Architecture

### Message Flow
1. **User Code** → `query()` function
2. **InternalClient** → `process_query()` method
3. **SubprocessCLITransport** → Spawns CLI subprocess
4. **CLI Process** → Outputs JSON messages to stdout
5. **Transport** → Reads and parses JSON lines
6. **Client** → Converts to Message objects
7. **User Code** → Receives Message objects via async iterator

### Key Components

#### `query()` Function
- Main entry point for the SDK
- Takes a `prompt` and optional `ClaudeCodeOptions`
- Returns an `AsyncIterator[Message]`
- Handles environment setup and client creation

#### Message Types
The SDK defines several message types:
- **UserMessage**: User input with content
- **AssistantMessage**: Claude's responses with content blocks
- **SystemMessage**: System events and status updates
- **ResultMessage**: Final result with cost, duration, and usage info

#### Content Blocks
Assistant messages can contain multiple content blocks:
- **TextBlock**: Plain text responses
- **ToolUseBlock**: Tool invocations (id, name, input)
- **ToolResultBlock**: Results from tool executions

#### Streaming Mechanism
- The CLI outputs JSON messages line by line to stdout
- Each line is a complete JSON object representing a message
- The transport reads these lines asynchronously and yields them
- Messages are parsed and converted to appropriate Python objects

## Current POC Issues

The current Streamlit implementation has several issues preventing true streaming:

1. **Message Container Recreation**: Lines 78-81 recreate the entire chat display on each message
2. **Session State Accumulation**: All messages are stored and re-rendered
3. **No Streaming Text**: Text blocks within assistant messages aren't streamed character by character
4. **UI Blocking**: The entire async operation blocks the UI until complete

## Recommendations for Streaming Fix

1. **Use Streamlit's native streaming**: Leverage `st.write_stream()` or incremental updates
2. **Separate message containers**: Create individual containers for each message
3. **Handle partial content**: Stream text content as it arrives
4. **Async UI updates**: Use Streamlit's async capabilities properly
5. **Message deduplication**: Avoid re-rendering existing messages