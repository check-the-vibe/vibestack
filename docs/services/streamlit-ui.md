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
- **Home dashboard:** Landing page that surfaces onboarding tasks, quick navigation links, and counts for sessions/templates.
- **Sessions workspace:** Consolidated selector with creation expander and tabs for Overview, Terminal, Workspace, and Template UI. Session launch supports working-directory presets, Codex CLI parameter toggles, and automatic log streaming.
- **Docs hub:** Curated Markdown browser for `.docs/` and `docs/` with tree previews and name filtering.
- **Templates manager:** Full CRUD tooling plus asset browser for built-in and user templates.
- **Services monitor:** Supervisor status table with restart/tail helpers; launching a tail spawns a hidden `script` session automatically.
- **Desktop bridge:** Embedded noVNC surface with a one-click link to open the desktop in a new tab.

## Source Highlights
- Main entrypoint: `streamlit_app/app.py`.
  - Uses `SessionManager` (`vibestack.sessions`) for backend operations.
  - Helper utilities handle workspace browsing, template page discovery, and dynamic execution of per-session Streamlit components.
- Additional pages live under `streamlit_app/pages/`.

## Common Tasks
- **Local iteration:** run `streamlit run streamlit_app/app.py --server.headless=true` during development, ensuring `PYTHONPATH` includes the repo root.
- **Adding pages:** drop a new Python file in `streamlit_app/pages/` with a `st.set_page_config` call and UI widgets.
- **Styling tweaks:** leverage Streamlit themes or custom CSS via `st.markdown` blocks.

## Troubleshooting
- `404 /ui/` → confirm Nginx proxy settings and that `streamlit` Supervisor program is running.
- Stale session data → call `manager.refresh_templates()` or reload the page (Streamlit caches results aggressively).
- Permission errors saving files → ensure session workspace paths are owned by `vibe` and writable.

## Design Guidelines
- Redirect `/` to `/ui/` so the Streamlit surface becomes the primary landing experience while keeping direct `/terminal` embeds functional.
- Consolidate navigation into Home, Sessions, Docs, Templates, Code, Services, Desktop; avoid nested session sub-pages that duplicate content.
- Place the session selector and create button on a shared horizontal row at the top of Sessions; reuse the component wherever session switching is required.
- Keep destructive controls (terminate, delete) under expandable sections or confirmation dialogs to avoid accidental clicks.
- Validate layouts at 1280×720 and ensure keyboard tab order follows the visual structure.
- Document new components inline with screenshots or short GIFs when behavior is non-obvious.

## Navigation Overview
- **Home:** Onboarding prompts, quick metrics, and shortcuts to the most common tools.
- **Sessions:** Unified management surface with selector, creation form, and per-session tabs.
- **Docs:** Centralized Markdown viewer for project references.
- **Templates:** Template CRUD operations and asset explorer.
- **Code:** Link-out to the VS Code tunnel with setup guidance.
- **Services:** Supervisor watchdog with restart/tail helpers.
- **Desktop:** Embedded noVNC experience for full desktop access.


Record deviations or UX issues in `TASKS.md` under "Follow-ups" so design adjustments remain visible to the team.
