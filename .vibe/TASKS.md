<!-- This document holds the tasks that have previously been completed, or need to be completed. Please ensure a consistent format for your tasks. Please add to this list when performing a task. You can also choose to add ideas for future work here, even if you are not intending to take those actions currently. -->

# Outcome 
The current POC does not render the chat messages in line as they happen, it waits till the whole of the claude call is done and then returns. Please fix this to respond as the messages are returned, following the examples to help. 

## Research
- Research the claude code python sdk, document your findings and learnings in .vibe/docs/* in a filename of your choosing
- Research the streamlit chat methods, document your findings and learnings in .vibe/docs/* in a filename of your choosing
- Research the best way to handle streaming responses using the Streamlit ChatMessage framework.
- Research the examples provided in Claude python sdk for streaming (https://github.com/anthropics/claude-code-sdk-python)
- Research Python documentation for similar guides on streaming, using yield, and handling async operations like the ones you will implement.
- Determine whether chat_message (https://docs.streamlit.io/develop/api-reference/chat/st.chat_message) or write_stream (https://docs.streamlit.io/develop/api-reference/write-magic/st.write_stream) is the best approach to solve the outcome. 

## POC
- Implement the chat interface for the claude page, which accurately renders each element of response from Claude as a chat message. Ensure that this is working correctly.
- Add logging to ensure that it is clear where actions are taken.

## Verification & Documentation
- Ensure all prior changes have made their way into a docker /devcontainer configuration that will be present when a container is built. The user will be verifying this change.