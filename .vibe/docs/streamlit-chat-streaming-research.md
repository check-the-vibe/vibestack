# Streamlit Chat and Streaming Research

## Overview
Streamlit provides two main approaches for implementing streaming chat interfaces:
1. `st.chat_message()` - Chat message containers
2. `st.write_stream()` - Streaming content display

## st.chat_message

### Features
- Creates a container for conversational UI elements
- Supports different message types: "user", "assistant", "human", "ai"
- Allows custom avatars (images, emojis, Material Symbols)
- Can contain multiple elements (text, charts, etc.)

### Usage Patterns
```python
# With notation
with st.chat_message("user"):
    st.write("Hello 👋")
    st.line_chart(data)

# Direct method calls
message = st.chat_message("assistant")
message.write("Hello human")
message.bar_chart(data)
```

### Limitations for Streaming
- Designed for static message containers
- Doesn't inherently support character-by-character streaming
- Better suited for complete messages

## st.write_stream

### Features
- Streams content from generators, iterables, or stream-like sequences
- Provides typewriter effect for string chunks
- Handles non-string data via st.write
- Automatically converts async generators to sync

### Key Benefits
- Native support for streaming text
- Works with OpenAI and LangChain streams
- Returns full response after streaming
- Ideal for real-time content updates

### Usage Example
```python
def response_generator():
    for word in response.split():
        yield word + " "
        time.sleep(0.05)

st.write_stream(response_generator)
```

## Best Approach for Claude Streaming

### Recommended Pattern
1. Use `st.chat_message()` for message containers
2. Use `st.write_stream()` within each message for streaming content
3. Maintain message history in session state
4. Create new containers only for new messages

### Implementation Strategy
```python
# For each new message
with st.chat_message(role):
    # Stream the content
    if streaming_content:
        st.write_stream(content_generator)
    else:
        st.write(content)
```

## Current POC Issues & Solutions

### Issues
1. Re-rendering entire chat history on each update
2. No character-by-character streaming
3. UI blocking during async operations

### Solutions
1. Create message containers once and update content
2. Use st.write_stream for assistant responses
3. Properly handle async/sync conversion
4. Implement proper message deduplication

## Conclusion
The optimal approach combines:
- `st.chat_message()` for message structure
- `st.write_stream()` for streaming assistant responses
- Proper session state management
- Incremental UI updates without full re-renders