# Session Templates

## Overview
Templates define repeatable tmux sessions for VibeStack. They bundle the command to launch, metadata such as labels and descriptions, and optional helper files to seed into a session workspace. Templates can be either built-in (shipped with the repo under `vibestack/templates/`) or user-defined (stored at runtime under `~/.vibestack/templates/`).

At startup the `SessionManager` merges built-in templates with anything in the user directory. The Streamlit UI and REST API expose the same list, so keeping template metadata accurate benefits every entry point.

## Template File Structure
Templates are JSON documents with the following common keys:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | Yes | Template identifier used by `vibestack-sessions` and the REST API. File name is `${name}.json`. |
| `label` | string | No | Friendly name shown in the UI. Defaults to `name` if omitted. |
| `command` | string | No | Command executed inside tmux. Empty string means "launch login shell". |
| `session_type` | enum | No | `"long_running"` (default) or `"one_off"`; controls lifecycle hints. |
| `description` | string | No | Appears in the Streamlit sidebar. |
| `working_dir` | string | No | Overrides the session workspace path when launching. |
| `env` | object | No | Extra environment variables injected before the command starts. |
| `post_create` | array | No | Reserved for future hooks; currently unused. |
| `include_files` | array | No | Files to copy into the session workspace on creation. Entries can be strings (`"relative/path.txt"`) or objects (`{"source": "assets/script.sh", "target": "script.sh"}`). |

When the session starts, VibeStack automatically adds `TASKS.md` to ensure every workspace has the task tracker. Additional files listed in `include_files` are resolved against these search roots (first match wins):
1. Built-in assets: `/home/vibe/vibestack/assets`
2. User assets: `~/.vibestack/assets`
3. Repository root (useful during development)

User-defined templates can also bundle custom assets by passing `include_sources` to the save call (see below); the files are copied under `~/.vibestack/assets/<template-name>/` and referenced automatically.

## Bundling Streamlit Pages
- Place `.py` files under a `streamlit/` directory inside the session workspace (e.g. `streamlit/control_panel.py`).
- When saving the template, include each page in `include_files` or pass their paths via `include_sources`; they will be stored under `~/.vibestack/assets/<template>/streamlit/` and copied into future sessions.
- During runtime the Streamlit app exposes these pages in the **Template UI** tab and executes them inline. Each page receives `st`, `session_metadata`, and `session_workspace` globals, so you can build custom controls without extra imports.
- Keep pages idempotent: they will re-run on every Streamlit refresh, so guard side effects accordingly.

## Creating a Template from a Working Session
1. **Launch and verify a session.** Use the Streamlit UI or `vibestack-sessions create` to start a session with your desired command / setup. Make sure the workspace contains any seed files you want future runs to receive.
2. **Collect the essentials.** Note the command (`SessionMetadata.command`), description, working directory, and any environment variables you configured manually. Decide which workspace files should be packaged as reusable assets.
3. **Prepare asset files.** Move or copy reusable files into a stable location (e.g. `/home/vibe/vibestack/assets/` during development). For ad-hoc assets, you can pass absolute paths when saving the template and they will be captured under the user asset directory.
4. **Author the template JSON.** Use the fields above to describe the session. A minimal example:
   ```json
   {
     "name": "pytest-session",
     "label": "Pytest Runner",
     "command": "poetry run pytest -q",
     "session_type": "one_off",
     "description": "Run the main test suite with concise output",
     "include_files": ["AGENTS.md", {"source": "pytest.ini", "target": "pytest.ini"}]
   }
   ```
5. **Persist the template.** Two common options:
   - **Python helper:**
     ```bash
     python3 - <<'PY'
     from pathlib import Path
     from vibestack import api

     payload = {
         "name": "pytest-session",
         "label": "Pytest Runner",
         "command": "poetry run pytest -q",
         "session_type": "one_off",
         "include_files": ["AGENTS.md"]
     }
     extra_files = [Path("/home/vibe/project/pytest.ini")]
     api.save_template(payload, include_sources=extra_files)
     PY
     ```
   - **REST API:**
     ```bash
     curl -sS -X POST http://localhost/admin/api/templates \
       -H 'Content-Type: application/json' \
       -d '{"payload": {"name": "pytest-session", "command": "poetry run pytest -q"}, "include_sources": ["/home/vibe/project/pytest.ini"]}'
     ```
6. **Validate.** Reload the Streamlit page or call `vibestack-sessions list` to ensure the new template appears with `"source": "user"`. Launch a fresh session from it to confirm the workspace assets and command run as expected.

## Maintenance Tips
- Store shared documentation (`AGENTS.md`, `TASKS.md`, service notes) in assets so every template can reference the same canonical version.
- Update `description` whenever the template behavior changes; downstream UIs surface it for discovery.
- Delete unused templates via `DELETE /admin/api/templates/{name}` or by removing the JSON file from `~/.vibestack/templates/`.
- Commit built-in templates (`vibestack/templates/*.json`) when you want the behavior to ship with the image. User templates live outside the repo and persist across container restarts.
