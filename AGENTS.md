# VibeStack Agent Guide

This container bundles everything required to run browser automation, REST APIs, and interactive shells for the VibeStack environment. Use this playbook to orient quickly, choose the right interface, and leave clear handoffs for the next agent.

## Quick Start
- Default working tree: `/home/vibe/sessions/codex-083811/artifacts` (mirror the repo structure when creating files).
- Runtime user: `vibe` (UID 1000). Root is available through `sudo` if absolutely necessary.
- Primary services are supervised; see `docs/README.md` for ports and reverse-proxy paths.
- Need a shell with tmux helpers? Hit `http://localhost/terminal/` (ttyd) or run `tmux attach` locally.

## Core Services
- **Playwright MCP** – Browser automation endpoint on port 7777 (`/mcp`, `/sse`).
- **Admin REST API** – FastAPI service on port 9000, proxied at `/admin/`. OpenAPI docs at `/admin/docs`.
- **Streamlit UI** – Web control surface at `/ui/` for launching sessions and inspecting workspaces.
- **noVNC Desktop** – Fluxbox desktop over WebSockets at `/computer/`.
- **ttyd Terminal** – Browser-based shell at `/terminal/` (also served at `/`).
Full notes, commands, and log locations live under `docs/services/`.

## Working with Sessions
- CLI: `vibestack-sessions list|show|create|one-off|send|kill|logs|jobs`.
  - Example: `vibestack-sessions create docs-refresh --template codex`.
  - One-off job: `vibestack-sessions one-off pytest-run "pytest -q"`.
- REST: `curl http://localhost/admin/api/sessions` (see `docs/services/admin-api.md`).
- Streamlit: Navigate to `/ui/` and use the sidebar to create or manage sessions.
- Every session gets a workspace under `/home/vibe/sessions/<name>/workspace` and a log at `/home/vibe/sessions/<name>/logs/tmux.log`.

## Template Workflow
- Templates live in `vibestack/templates/` (built-in) and `~/.vibestack/templates/` (user-defined).
- Read the end-to-end guide in `docs/templates.md` for field definitions and automation examples.
- Quick capture flow:
  1. Launch and verify the session manually.
  2. Collect the command, description, env, and reusable files.
  3. Call `vibestack.api.save_template(...)` or `POST /admin/api/templates`.
  4. Validate with `vibestack-sessions create <name> --template <template>`.
- Use `include_sources` when saving to bundle files automatically under `~/.vibestack/assets/<template>/`.
- Want template-specific UI? Drop `.py` files under `streamlit/` in the workspace before saving and include them via `include_sources`; they appear inside the Streamlit app's **Template UI** tab.

## Logs & Troubleshooting
- Supervisor config: `/etc/supervisor/conf.d/supervisord.conf` (source file in repo root).
- Service logs: `/var/log/supervisor/*.log` plus dedicated files for ttyd and nginx.
- Nginx routing: `/etc/nginx/nginx.conf` (see repo copy for edits).
- Health check targets `http://localhost:${NOVNC_PORT}/vnc.html` – if it fails, inspect `xvfb`, `x11vnc`, and `novnc`.

## Collaboration Checklist
- Record objectives, constraints, and progress in the table below before handing off.
- Note any running sessions or background jobs you started.
- Update docs if you change ports, commands, or template behavior.

| Section | Notes |
| --- | --- |
| Objective | |
| Key Constraints | |
| Resources | |
| Progress Log | |
| Open Questions | |

Refer to `docs/README.md` and the files under `docs/services/` whenever you need deeper context on the stack.
