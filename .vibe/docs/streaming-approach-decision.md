# Streaming Approach Decision

## Decision: Hybrid Approach with st.chat_message + st.write_stream

After researching both `st.chat_message` and `st.write_stream`, the optimal approach is to use them together:

### Architecture
1. **st.chat_message**: For message containers and structure
2. **st.write_stream**: For streaming assistant content within messages
3. **Session State**: For message history management
4. **Async-to-Sync Conversion**: Custom generator for Claude messages

### Why This Approach?

#### Advantages
- **True Streaming**: Content appears as it's generated
- **Clean UI**: Proper message separation and avatars
- **Performance**: No re-rendering of existing messages
- **User Experience**: Typewriter effect for assistant responses

#### Implementation Pattern
```python
# For user messages (static)
with st.chat_message("user"):
    st.write(user_input)

# For assistant messages (streaming)
with st.chat_message("assistant"):
    # Stream the response
    response_text = st.write_stream(claude_message_generator())
    # Store complete response in session state
```

### Technical Details

#### Message Flow
1. User submits prompt
2. Create user message container immediately
3. Create assistant message container
4. Stream assistant content using st.write_stream
5. Store complete messages in session state
6. Display historical messages on page reload

#### Async Handling
- Use threading to prevent UI blocking
- Convert async Claude messages to sync generator
- Yield text chunks for smooth streaming

### Rejected Alternatives

1. **Pure st.chat_message**: No native streaming support
2. **Pure st.write_stream**: Loses chat structure
3. **Manual DOM updates**: Too complex and fragile
4. **Full re-render**: Current issue - poor performance

## Conclusion
The hybrid approach provides the best balance of:
- Real-time streaming feedback
- Clean chat interface
- Good performance
- Maintainable code