# VibeStack Programmatic API

The `vibestack.api` module exposes a small set of helpers for integrating sessions into other Python tooling (Streamlit, FastAPI, MCP servers, etc.).

## Quick start
```python
from vibestack.api import create_session, enqueue_one_off, list_sessions, tail_log

# Launch an interactive Codex session
metadata = create_session("codex-demo", template="codex")
print(metadata["workspace_path"])  # inspect artifacts folder

# Queue a short-run job
job = enqueue_one_off("lint-job", "ruff check .")
print(job["status"])  # "running" or "completed"

# Poll sessions
for session in list_sessions():
    print(session["name"], session["status"])

# Tail logs
print(tail_log("lint-job", lines=40))
```

## Functions

| Function | Description |
| --- | --- |
| `get_manager(session_root=None)` | Returns a memoised `SessionManager`. Supplying `session_root` bypasses the cache. |
| `list_sessions(session_root=None)` | Returns session metadata dictionaries (same shape as `SessionMetadata.to_dict()`). |
| `get_session(name, session_root=None)` | Metadata for a single session or `None` if missing. |
| `create_session(name, template='bash', command=None, description=None, session_root=None)` | Launches a long-running session. |
| `enqueue_one_off(name, command, template='script', description=None, session_root=None)` | Creates a short-run job with exit-code tracking. |
| `send_text(name, text, enter=True, session_root=None)` | Sends keystrokes to the primary pane (defaults to appending ENTER). |
| `kill_session(name, session_root=None)` | Terminates the tmux session if active. |
| `tail_log(name, lines=200, session_root=None)` | Returns the last N log lines. |
| `list_jobs(session_root=None)` | Returns queued/completed job records (from `queue.json`). |
| `list_templates()` | Returns all templates (built-in and user) with sources. |
| `save_template(payload, include_sources=None)` | Saves a template JSON file; optionally copies session files into the user asset store. |
| `delete_template(name)` | Removes a user-defined template. |

## Notes
- All helper functions reuse the same underlying `SessionManager`, so operations remain consistent with the Streamlit UI.
- Template helpers mirror the behaviour of the Templates Streamlit page, including copying workspace files for portability.
- When interfacing with web frameworks, keep long-running operations off the request thread; these helpers are synchronous wrappers.
