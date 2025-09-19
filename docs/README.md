# VibeStack Runtime Overview

VibeStack bundles several long-lived services inside a single container image. Supervisor keeps them running, while Nginx is the public HTTP entrypoint that routes traffic to each upstream. Use this directory to orient new coding agents before they touch the system.

## Service Map
| Service | Role | Supervisor Program | Internal Port | External Path |
| --- | --- | --- | --- | --- |
| Playwright MCP | Headless browser automation endpoint for Model Context Protocol clients | `playwright-mcp` | 7777 | `/mcp`, `/sse` |
| Admin REST API | FastAPI wrapper around the session manager | `vibestack-api` | 9000 | `/admin/` |
| Streamlit UI | Browser UI for launching sessions and managing workspaces | `streamlit` | 8501 | `/ui/` |
| noVNC Desktop | Web-based remote desktop backed by Fluxbox | `novnc` (depends on `xvfb`, `x11vnc`, `fluxbox`) | 6080 (WebSockets) | `/computer/` |
| ttyd Terminal | Browser-based terminal with tmux helpers | `ttyd` | 7681 | `/terminal/`, `/` |

See the individual service notes under `services/` for deeper configuration and troubleshooting guidance.

## Process Supervision
- Supervisor definition: `supervisord.conf` in the repository root governs startup order, log locations, and environment variables for every service.
- Default command: the container entrypoint (`entrypoint.sh`) launches Supervisor unless another command is passed. Passwords for `root` and `vibe` are set here using `ROOT_PASSWORD` and `VIBE_PASSWORD`.
- User context: long-lived services run as the `vibe` user with `PYTHONPATH` pointing at `/home/vibe` so Python code can import the `vibestack` package.

## HTTP Routing
- Nginx front door: `nginx.conf` proxies each URI prefix to the appropriate upstream port. Any new HTTP service should be registered here.
- Health check: Dockerfile defines `HEALTHCHECK` against `http://localhost:${NOVNC_PORT}/vnc.html` to verify the desktop surface is live.

## Source Layout Highlights
- Python backend lives in `/home/vibe/vibestack` at runtime (syncs from `vibestack/` in the build context).
- Streamlit front-end ships from `streamlit_app/` and is copied to `/home/vibe/streamlit`.
- Helper CLI scripts such as `bin/vibestack-ttyd-entry` and `bin/vibestack-sessions` are linked into `/usr/local/bin` for convenience.

## Next Steps for Agents
1. Read the relevant service guide in `services/`.
2. Inspect `supervisord.conf` and `nginx.conf` if you need to adjust ports, environment variables, or routing.
3. Use the Streamlit UI or the REST API to launch a test session before making invasive changes.
4. Keep docs up to date when processes, ports, or dependencies change.
