# Playwright MCP Service

## Purpose
Provides a Model Context Protocol (MCP) bridge that exposes a Chromium-driven Playwright agent. Coding agents use it to execute deterministic browser automation without leaving the container.

## Startup & Lifecycle
- Supervisor program: `playwright-mcp` (see `supervisord.conf`). Starts after the desktop stack so Xvfb is available.
- Command: `npx -y @playwright/mcp@latest --viewport-size "1280, 720" --no-sandbox --port 7777 --host 0.0.0.0`.
- User: runs as `vibe` with `HOME`, `VIBESTACK_HOME`, and `PYTHONPATH` exported.
- Logs: `/var/log/supervisor/playwright.log` (stdout and stderr combined).

## Routing & Access
- Internal port: `7777`.
- Nginx routes:
  - `/mcp` → `http://localhost:7777/mcp` (REST-style control plane).
  - `/sse` → `http://localhost:7777/sse` (server-sent events stream).
- Health: no dedicated probe; rely on Supervisor status or check `curl -i http://localhost/mcp` for a 200 response.

## Dependencies
- Node.js LTS and `@playwright/mcp` installed globally during the Docker build.
- Chromium browser installed via `npx -y playwright install chrome`.
- Xvfb virtual display (program `xvfb`) must be running to provide a framebuffer.

## Common Tasks
- **Smoke test:** `curl http://localhost/mcp | jq` from inside the container to confirm the service responds.
- **Update Playwright MCP:** adjust the `npm install -g playwright-mcp` line in the Dockerfile and rebuild.
- **Viewport tweaks:** change the `--viewport-size` flag in `supervisord.conf` and restart the process with `supervisorctl restart playwright-mcp`.

## Troubleshooting
- `ECONNREFUSED` → ensure Supervisor started the service and nothing else is bound to port 7777.
- Rendering issues → verify Xvfb is running (`supervisorctl status xvfb`) and that `RESOLUTION` matches expectations.
- Chromium missing → rerun `npx -y playwright install chrome`; check build logs to make sure the dependency step succeeds.
