Below is a concise, Python-centric recipe for standing up an MCP server that exposes your `pyscreenrec` start/stop recording calls as tools. We’ll use **FastMCP**, which gives you a decorator-based, Pythonic interface for defining MCP tools with virtually zero boilerplate.

---

## 1. Install dependencies

```bash
pip install fastmcp pyscreenrec
```

* **FastMCP**: the Python MCP framework you’ll use to expose functions over the Model Context Protocol ([github.com][1])
* **pyscreenrec**: a lightweight screen-recording library whose `start_recording`/`stop_recording` methods we’ll wrap ([pypi.org][2])

---

## 2. Define your MCP server

Create `server.py`:

```python
from fastmcp import FastMCP
from pyscreenrec import ScreenRecorder

# Instantiate the recorder
recorder = ScreenRecorder()

# Create the MCP server
mcp = FastMCP(name="ScreenRecorder")

# Expose start_recording as an LLM‐callable tool
@mcp.tool()
def start_record(output_path: str = "recording.mp4") -> str:
    """Begin screen capture; output to the given file."""
    recorder.start_recording(output_path)
    return f"Recording started → {output_path}"

# Expose stop_recording likewise
@y mcp.tool()
def stop_record() -> str:
    """End screen capture and flush video file."""
    recorder.stop_recording()
    return "Recording stopped and saved."

if __name__ == "__main__":
    # Launch as an SSE server on localhost:8000
    mcp.run(transport="sse", host="127.0.0.1", port=8000)
```

* `@mcp.tool()` wraps your Python functions so any MCP-compliant LLM client can invoke them directly ([github.com][3])
* We use **Server-Sent Events (SSE)** transport to allow remote clients (e.g. Claude Desktop) to connect over HTTP ([pondhouse-data.com][4])

---

## 3. Running and using the server

1. **Start** your server:

   ```bash
   python server.py
   ```
2. **Connect** from any MCP client (e.g. via `fastmcp run server.py` or by pointing your client at `http://127.0.0.1:8000`).
3. **Invoke** the tools in your LLM prompt:

   ```json
   {"id":"start_record", "arguments":{"output_path":"session.mp4"}}
   ```

   …then later:

   ```json
   {"id":"stop_record","arguments":{}}
   ```

Those calls will kick off and terminate the recording thread inside `pyscreenrec` for you, with clean integration into any MCP-aware LLM workflow.

[1]: https://github.com/jlowin/fastmcp?utm_source=chatgpt.com "jlowin/fastmcp: The fast, Pythonic way to build MCP servers and clients"
[2]: https://pypi.org/project/pyscreenrec/?utm_source=chatgpt.com "pyscreenrec - PyPI"
[3]: https://github.com/AI-App/JLowin.FastMCP?utm_source=chatgpt.com "AI-App/JLowin.FastMCP: The fast, Pythonic way to build MCP ..."
[4]: https://www.pondhouse-data.com/blog/create-mcp-server-with-fastmcp?utm_source=chatgpt.com "Creating an MCP Server Using FastMCP: A Comprehensive Guide"
