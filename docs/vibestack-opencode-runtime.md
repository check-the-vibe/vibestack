# VibeStack Runtime Guide for Coding LLMs (opencode)

This guide explains how coding agents and LLMs operate inside the VibeStack container: what’s available, where services live, and how to surface your own dev servers reliably (with or without ngrok). Copy-paste commands are tuned for this repo and image.

## Environment Basics
- Base OS: Ubuntu (containerized)
- Default user: `vibe` (owns workspace and services)
- Shell/term: `ttyd` + tmux
- Desktop: XFCE via noVNC
- Python: 3.10 with repo on `PYTHONPATH`
- Node & build tools: preinstalled in image
- VS Code tunnel: supervised, CLI-based

## Ports, Routes, and Proxies
All public access runs through Nginx on port 80 inside the container. The helper script maps host port 3000 → container 80.

- UI: `/ui/` → `localhost:8501` (Streamlit)
- Terminal: `/terminal/` → `localhost:7681` (ttyd)
- Desktop: `/computer/` (+ `/computer/websockify`) → `localhost:6080` (noVNC)
- Admin API: `/admin/` → `127.0.0.1:9000/` (FastAPI, REST)
- MCP: `/mcp` and `/mcp/` → `127.0.0.1:9100/` (Streamable HTTP)
- Dev service proxies: `/services/3000/ … /services/3004/` forward to `localhost:<port>` (WebSocket upgrades supported)
- Root fallback: `/` → `localhost:7681` (ttyd)
- ChatGPT link shims: `/VibeStack/*` → `/link/*` → REST link helpers
- Extension files: `/extension/` → `/home/vibe/vibestack-extension/`

See `nginx.conf` for exact headers and forwarding behavior.

## Startup and ngrok
Use the helper to build and run the container with sensible defaults and log streaming support.

- Build + run: `./startup.sh` (maps host `3000:80`, `1455:1456`). Optionally mount a host folder at `/projects` with `./startup.sh --projects <path>` (relative and `~` supported).
- Follow logs: `./startup.sh follow`
- Base URL propagation:
  - `./startup.sh --base-url https://your-domain.example` sets `VIBESTACK_PUBLIC_BASE_URL` in the container.
  - If omitted, the script tries to detect an ngrok HTTPS tunnel bound to host port 3000 via the local API at `127.0.0.1:4040` and exports the detected URL as `VIBESTACK_PUBLIC_BASE_URL`.
  - If detection fails, services still run; public links default to the value in `vibestack/settings.py` until updated.

Tip: You can change the persisted base URL from the Streamlit UI’s MCP page; it writes to `~/.vibestack/settings.json`.

## Access URLs (host perspective)
Assuming `./startup.sh` mapped host port 3000 → container 80:
- Terminal: `http://localhost:3000/terminal/` (root `/` also lands in terminal)
- UI: `http://localhost:3000/ui/`
- Desktop: `http://localhost:3000/computer/`
- REST via proxy: `http://localhost:3000/admin/api/...`
- MCP: `http://localhost:3000/mcp`
- Dev servers: `http://localhost:3000/services/3000/` to `3004/`

If you expose via ngrok on host port 3000, replace `http://localhost:3000` with the detected ngrok HTTPS URL.

## Session Workflows
You can control sessions via CLI, REST, Streamlit UI, or MCP.

- CLI (`bin/vibe`): uses repo on `PYTHONPATH` and runs `vibestack.sessions.cli`
  - List: `bin/vibe list`
  - Create: `bin/vibe create --template bash my-session`
  - Attach: `bin/vibe attach my-session`
  - One-off job: `bin/vibe oneoff --template script job-foo -- pytest -q`

- REST (proxied under `/admin/api`): examples
  - List: `GET /admin/api/sessions`
  - Create: `POST /admin/api/sessions` with `{ "name": "demo", "template": "bash" }`
  - Tail log: `GET /admin/api/sessions/demo/log?lines=200`
  - Send input: `POST /admin/api/sessions/demo/input` with `{ "text": "ls -la", "enter": true }`

- Streamlit UI: `/ui/` → Sessions page for create/attach/tail.

- MCP (Streamable HTTP at `/mcp`):
  - Inside container: `http://localhost/mcp`
  - Via host mapping (through Nginx): `http://localhost:3000/mcp`
  - Quick test: `python3 examples/mcp_runner.py` (set `VIBESTACK_MCP_URL` if needed)

Session metadata returned by API includes `session_url` which points at the Streamlit Sessions page for that session, using `VIBESTACK_PUBLIC_BASE_URL` when set.

## Filesystem Layout and Persistence
- Session root: managed by `vibestack.sessions.SessionManager` (default under `/home/vibe/.vibestack/sessions` unless overridden)
- Per-session structure:
  - `metadata.json` – canonical session record
  - `console.log` – tmux-captured output
  - `artifacts/` – workspace path shown in the UI
- Job queue: `queue.json` stored at the session root
- Templates: built-ins under `vibestack/templates/`; user templates persisted via REST/MCP save endpoints

Note: Persistent Codex state mounts to `/data/codex` (see `startup.sh`). Host project folders mounted from the host are available under `/projects` inside the container. Use `./startup.sh --projects <path>` to specify which host directory to bind mount.

## Common Dev Stacks via Proxies
Run your server on one of the allocated ports (3000–3004) and access it under `/services/<port>/`.

- Vite/React: `npm run dev -- --port 3000` → `…/services/3000/`
- Next.js: `next dev -p 3001` → `…/services/3001/`
- FastAPI (alt app): `uvicorn app:app --port 3002 --host 0.0.0.0` → `…/services/3002/`
- Flask: `flask run -p 3003 -h 0.0.0.0` → `…/services/3003/`
- Socket.IO server: bind to `3004` → `…/services/3004/`

WebSocket upgrades are forwarded end-to-end for hot reload and real-time transports.

## VS Code Tunnel
- Supervised command: `vibestack-code-tunnel` (wraps `code tunnel --accept-server-license-terms`)
- Authenticate by tailing `/var/log/supervisor/vscode-tunnel.log` and opening the device login URL
- Connect from the desktop VS Code client to the advertised tunnel name (default `vibestack`)

See `docs/services/vscode-tunnel.md` for knobs and tips.

## Desktop and Terminal
- Terminal: `/terminal/` (ttyd); also bridges root `/`
- Desktop: `/computer/` (noVNC) with optimized params for high-DPI devices
- Open a desktop terminal if you prefer a graphical shell; both shells share the same user and environment

## Security and Settings
- Do not commit real credentials. Put new env vars in `.env.example`
- Keep `VIBESTACK_PUBLIC_BASE_URL` updated when tunnels change; Streamlit’s MCP page writes to `~/.vibestack/settings.json`
- Confirm port and path consistency when editing `supervisord.conf` or `nginx.conf`

## Troubleshooting
- 404 under `/ui/`: ensure Streamlit supervisor program is running
- Terminal blank page: check `/var/log/ttyd.err`; verify port 7681 listener
- `/mcp` client errors: confirm request goes through Nginx, not legacy SSE endpoints
- Dev server unreachable: ensure it listens on the chosen port and `0.0.0.0`; then open `/services/<port>/`
- Session not visible: inspect `/var/log/supervisor/vibestack-api.log` and `~/.vibestack/sessions`

## Quick Reference
- Build/run container: `./startup.sh [follow] [--base-url=https://<public-host>]`
- UI: `/ui/` • Terminal: `/terminal/` • Desktop: `/computer/`
- REST: `/admin/api/…` • MCP: `/mcp`
- Dev proxies: `/services/3000/…` → `localhost:3000` (similarly `3001–3004`)
- CLI: `bin/vibe list|create|attach|oneoff`
