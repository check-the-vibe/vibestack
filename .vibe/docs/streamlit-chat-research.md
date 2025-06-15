# Streamlit Chat Interface Research

## Overview
Streamlit provides built-in chat elements designed for building conversational applications. These elements can be used together or separately.

## Key Chat Elements

### 1. st.chat_message
Creates a chat message container that can display messages from users or the app.

**Features:**
- Can embed any Streamlit element (charts, tables, text, etc.)
- Supports different message roles (user, assistant, etc.)
- Provides consistent styling for chat interfaces

**Basic Example:**
```python
with st.chat_message("user"):
    st.write("Hello 👋")
    st.line_chart(np.random.randn(30, 3))
```

### 2. st.chat_input
Displays a chat input widget for users to type and send messages.

**Features:**
- Returns the user's input when they press Enter
- Can have placeholder text
- Clears automatically after submission

**Basic Example:**
```python
prompt = st.chat_input("Say something")
if prompt:
    st.write(f"The user has sent: {prompt}")
```

### 3. st.write_stream
Writes generators or streams with a typewriter effect - perfect for streaming AI responses.

**Example:**
```python
import time

def stream_data():
    for word in text.split():
        yield word + " "
        time.sleep(0.02)

st.write_stream(stream_data)
```

## Building a Chat Interface

### Basic Chat Pattern
```python
# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages from history on app rerun
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# React to user input
if prompt := st.chat_input("What is up?"):
    # Display user message in chat message container
    with st.chat_message("user"):
        st.markdown(prompt)
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Display assistant response in chat message container
    with st.chat_message("assistant"):
        response = "Echo: " + prompt
        st.markdown(response)
    # Add assistant response to chat history
    st.session_state.messages.append({"role": "assistant", "content": response})
```

## Real-time Streaming Pattern
For streaming responses (like from Claude Code SDK):

```python
with st.chat_message("assistant"):
    message_placeholder = st.empty()
    full_response = ""
    
    # Simulate stream of response
    for chunk in response_generator():
        full_response += chunk
        message_placeholder.markdown(full_response + "▌")
    
    message_placeholder.markdown(full_response)
```

## Integration Considerations for Claude Code
1. **Session State**: Use `st.session_state` to maintain chat history
2. **Async Handling**: May need to use `asyncio` with Streamlit for Claude SDK
3. **Streaming**: Use placeholders and `st.write_stream` for real-time responses
4. **Multiple Containers**: Can show code, terminal output, etc. within chat messages