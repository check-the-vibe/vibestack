# Streamlit User Interface

## Purpose
Interactive dashboard for launching VibeStack sessions, queuing one-off jobs, and browsing workspace files directly from a browser. Targets power users and coding agents that prefer a graphical control plane over the REST API.

## Startup & Lifecycle
- Supervisor program: `streamlit`.
- Command: `streamlit run /home/vibe/streamlit/app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true --server.enableCORS=false --server.baseUrlPath=ui`.
- Runs as the `vibe` user so it can read/write session workspaces.
- Logs: `/var/log/supervisor/streamlit.log`.

## Routing & Access
- Internal port: `8501`.
- Nginx proxy: `/ui/` prefix (app expects this base URL via `--server.baseUrlPath` flag).

## Key UI Features
- **Session launcher:** sidebar form to select templates, override commands, and create named sessions.
- **Terminal page:** embeds the tmux pane for the active session and auto-sends an extra ENTER after commands so Codex actions start without manual intervention.
- **Workspace tab:** browse and edit text files for the active session, with download support for binaries.
- **Template UI tab:** discover `.py` files under `streamlit/` in the session workspace and run them inline so templates can deliver custom controls.
- **Templates & Desktop links:** quick access in the sidebar to template management and the noVNC desktop view (`/computer/`).
- **Sessions page:** review every session (including stopped ones), inspect metadata, focus running sessions, and terminate lingering jobs from a dedicated view.
- **Session data table:** list all sessions with status, template, timestamps, and quick selection.

## Source Highlights
- Main entrypoint: `streamlit_app/app.py`.
  - Uses `SessionManager` (`vibestack.sessions`) for backend operations.
  - Helper utilities handle workspace browsing, template page discovery, and dynamic execution of per-session Streamlit components.
- Additional pages live under `streamlit_app/pages/` (create new files here for multi-page workflows).

## Common Tasks
- **Local iteration:** run `streamlit run streamlit_app/app.py --server.headless=true` during development, ensuring `PYTHONPATH` includes the repo root.
- **Adding pages:** drop a new Python file in `streamlit_app/pages/` with a `st.set_page_config` call and UI widgets.
- **Styling tweaks:** leverage Streamlit themes or custom CSS via `st.markdown` blocks.

## Troubleshooting
- `404 /ui/` → confirm Nginx proxy settings and that `streamlit` Supervisor program is running.
- Stale session data → call `manager.refresh_templates()` or reload the page (Streamlit caches results aggressively).
- Permission errors saving files → ensure session workspace paths are owned by `vibe` and writable.
