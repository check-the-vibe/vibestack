# VibeStack Runtime Overview

VibeStack bundles several long-lived services inside a single container image. Supervisor keeps them running, while Nginx is the public HTTP entrypoint that routes traffic to each upstream. Use this directory to orient new coding agents before they touch the system.

## Service Map
| Service | Role | Supervisor Program | Internal Port | External Path |
| --- | --- | --- | --- | --- |
| Admin REST API | FastAPI wrapper around the session manager | `vibestack-api` | 9000 | `/admin/` |
| MCP Session API | Model Context Protocol interface to the session manager | `vibestack-mcp` | 9100 | `/mcp/` |
| Streamlit UI | Browser UI for launching sessions and managing workspaces | `streamlit` | 8501 | `/ui/` |
| noVNC Desktop | Web-based remote desktop backed by XFCE4 | `novnc` (depends on `xvfb`, `x11vnc`, `xfce4`) | 6080 (WebSockets) | `/computer/` |
| ttyd Terminal | Browser-based terminal with tmux helpers | `ttyd` | 7681 | `/terminal/`, `/` |
| VS Code Tunnel | Visual Studio Code remote tunnel endpoint | `vscode-tunnel` | Outbound only | n/a |
| Dev Service Proxies | Generic HTTP pass-through for sandboxed tools | n/a | 3000-3004 | `/services/<port>/` |

See the individual service notes under `services/` for deeper configuration and troubleshooting guidance. The new MCP service guide also documents the `examples/mcp_runner.py` smoke test and IDE integration steps.

## Process Supervision
- Supervisor definition: `supervisord.conf` in the repository root governs startup order, log locations, and environment variables for every service.
- Default command: the container entrypoint (`entrypoint.sh`) launches Supervisor unless another command is passed. Passwords for `root` and `vibe` are set here using `ROOT_PASSWORD` and `VIBE_PASSWORD`.
- User context: long-lived services run as the `vibe` user with `PYTHONPATH` pointing at `/home/vibe` so Python code can import the `vibestack` package.

## HTTP Routing
- Nginx front door: `nginx.conf` proxies each URI prefix to the appropriate upstream port. Any new HTTP service should be registered here.
- Health check: Dockerfile defines `HEALTHCHECK` against `http://localhost:${NOVNC_PORT}/vnc.html` to verify the desktop surface is live.

## Source Layout Highlights
- Home bundle assets now live directly in the repo root (`bin/`, `streamlit_app/`, `vibestack/`, `xfce-startup`, `Xresources`, etc.) and are copied into `/home/vibe/` during the image build.
- Python backend lives in `/home/vibe/vibestack` at runtime (populated from the repository `vibestack/` directory).
- Streamlit front-end ships from the repository `streamlit_app/` directory and is copied to `/home/vibe/streamlit`.
- Helper CLI scripts such as `bin/vibestack-ttyd-entry` and `bin/vibe` are linked into `/usr/local/bin` for convenience.

## Next Steps for Agents
1. Review the [Repository Guidelines](../AGENTS.md) and the companion [overview](repository-guidelines-overview.md) before editing.
1. Start with `docs/repo-layout.md` for a map of repository paths and runtime copy behavior.
1. Read the relevant service guide in `services/`.
1. Inspect `supervisord.conf` and `nginx.conf` if you need to adjust ports, environment variables, or routing.
1. Use the Streamlit UI or the REST API to launch a test session before making invasive changes.
1. Keep docs up to date when processes, ports, or dependencies change.
1. Review `docs/gpt-5-codex.md` before kicking off complex Codex work and add new heuristics as you discover them.
