# Python Async and Streaming Research

## Async Generators in Python

### Basic Concepts
- **Async Generator**: A function that uses `async def` and `yield`
- **AsyncIterator**: An object that implements `__aiter__()` and `__anext__()`
- **async for**: Used to iterate over async generators

### Example Pattern
```python
async def stream_data():
    for i in range(10):
        yield f"Data chunk {i}"
        await asyncio.sleep(0.1)

async def consume():
    async for chunk in stream_data():
        print(chunk)
```

## Converting Async to Sync for Streamlit

### Challenge
- Streamlit runs in a synchronous context
- Claude SDK returns async iterators
- Need to bridge async/sync gap

### Solutions

#### 1. asyncio.run() - Current Approach
```python
asyncio.run(run_claude_session(prompt, max_turns))
```
**Issue**: Blocks until entire async operation completes

#### 2. Generator Wrapper
```python
def sync_generator(async_gen):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        while True:
            yield loop.run_until_complete(async_gen.__anext__())
    except StopAsyncIteration:
        pass
    finally:
        loop.close()
```

#### 3. Threading Approach
```python
import threading
import queue

def async_to_sync_generator(async_gen):
    q = queue.Queue()
    
    async def _runner():
        try:
            async for item in async_gen:
                q.put(item)
        finally:
            q.put(StopIteration)
    
    thread = threading.Thread(target=lambda: asyncio.run(_runner()))
    thread.start()
    
    while True:
        item = q.get()
        if item is StopIteration:
            break
        yield item
```

## Streamlit-Specific Considerations

### st.write_stream Requirements
- Expects a synchronous generator or iterable
- Automatically handles async generators by converting them
- Works best with yielding strings for typewriter effect

### Optimal Pattern for Claude + Streamlit
```python
def message_generator(async_messages):
    """Convert async Claude messages to sync generator for Streamlit"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        while True:
            message = loop.run_until_complete(async_messages.__anext__())
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        # Yield text in chunks for streaming effect
                        for word in block.text.split():
                            yield word + " "
    except StopAsyncIteration:
        pass
    finally:
        loop.close()
```

## Key Insights
1. Streamlit's `st.write_stream()` handles async-to-sync conversion internally
2. For custom streaming, manual conversion is needed
3. Threading can help prevent UI blocking
4. Yielding smaller chunks creates better streaming UX