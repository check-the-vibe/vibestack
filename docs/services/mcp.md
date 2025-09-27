# MCP Session Service

## Purpose
Expose VibeStack's session manager over the Model Context Protocol (MCP) so IDEs and copilots can provision, inspect, and control sessions without touching the REST API directly. The service reuses the same business logic as `vibestack.api` and mirrors the tool surface area (sessions, jobs, templates, log tailing).

## Startup & Lifecycle
- Supervisor program: `vibestack-mcp`.
- Command: `/usr/bin/python3 -m uvicorn vibestack.mcp.server:app --host 0.0.0.0 --port 9100`.
- Runs as the `vibe` user with `PYTHONPATH=/home/vibe` so the server can import local modules.
- Logs: `/var/log/supervisor/vibestack-mcp.log`.

## Routing & Access
- Internal port: `9100` (TCP).
- Nginx proxy: `/mcp` → `http://localhost:9100/`.
- Streamable HTTP endpoint (inside container): `http://localhost/mcp`.
- Host mapping (via `startup.sh`): `http://localhost:90/mcp`.
- The server exposes the full streamable HTTP handshake (`POST /mcp`, `GET /mcp`, `DELETE /mcp`) and emits the `Mcp-Session-Id` header for reconnection.
- The Starlette app wires `_handle_streamable_http(scope, receive, send)` through a top-level `Mount` route so `StreamableHTTPSessionManager.handle_request(...)` receives the full ASGI triple; mounting keeps the raw ASGI callables intact, whereas the generic `Route` wrapper would coerce them into a `Request`/`Response` cycle and break the transport.

## Quick Smoke Test
Run the helper script after the container is live:

```bash
python3 examples/mcp_runner.py
```

Environment variables:
- `VIBESTACK_MCP_URL` (optional) – override the default streamable HTTP URL if the proxy is bound to a different host or port.

> Tip: when running tools from the host machine (outside the container) point them at `http://localhost:90/mcp`; inside the container the same proxy is available at `http://localhost/mcp`.

The script uses the `modelcontextprotocol/python-sdk` streamable HTTP client to connect, list templates, create a demo session, and print the resulting metadata. The session is created with a random suffix and will show up in the Streamlit UI under **Sessions**.

## Session URLs
- Session metadata now includes `session_url`, pointing to the Streamlit Sessions page (for example `https://8cf01ce6152b.ngrok.app/ui/Sessions?session=demo`).
- MCP exposes a `get_session_url` tool that returns the same link when provided a session name.
- Configure the public base domain via the **MCP** page in Streamlit; changes are persisted to `~/.vibestack/settings.json` and applied by the MCP service automatically.
- Set `VIBESTACK_SESSION_FOLLOW_BASE` to temporarily override the configured value (useful for ad-hoc tunnels).

## IDE & Assistant Integration

### GitHub Copilot in VS Code
1. Ensure Copilot MCP support is enabled (Insiders build or 1.90+).
2. Create or update `~/.config/github-copilot/mcp.json`:
   ```json
   {
     "servers": [
       {
         "name": "VibeStack",
         "type": "streamable-http",
         "endpoint": "http://localhost:90/mcp"
       }
     ]
   }
   ```
3. Reload VS Code. Copilot Chat now exposes the **VibeStack** server – ask `@VibeStack list_sessions` to confirm connectivity.
4. Tail the VS Code tunnel logs from Streamlit (**Onboarding** panel) to capture the login URL when the tunnel requests authentication.

### Codex CLI
1. Rebuild the container (`./startup.sh`) so the updated dependencies (`mcp[cli]`, HTTP tooling) are available.
2. Add the endpoint to the Codex MCP config (default location `~/.codex/mcp/endpoints.json`):
   ```json
   {
     "servers": [
       {
         "name": "vibestack",
         "type": "streamable-http",
         "endpoint": "http://localhost:90/mcp"
       }
     ]
   }
   ```
3. Restart the Codex CLI (or run `codex mcp reload`) and issue `mcp vibestack list_templates` to verify the bridge.

### ChatGPT (Developer Mode)
1. Open ChatGPT, switch to **Developer**.
2. Under **My servers → Add server**, choose **Streamable HTTP**, supply:
   - Name: `VibeStack`
   - URL: `http://localhost:90/mcp`
3. Save and connect. Run `list_sessions` or `create_session` from the in-app console to validate.

### Terminal Input
- Invoke the `send_input` tool with the session `name`, the `text` you want to type, and optionally the `enter` flag.
- `enter` accepts booleans or truthy strings (`"press"`, `"enter"`, `"return"`) to press the Enter key after the payload. Set it to `false`/`"skip"` to queue text without executing it.
- Example payload: `{ "name": "demo", "text": "ls -la", "enter": true }` queues the command and sends Enter in a single call.
- Send `{ "name": "demo", "text": "", "enter": "press" }` to transmit just an Enter keystroke, matching the Streamlit UI behaviour when you click **Send**.

## Troubleshooting
- **Missing `Mcp-Session-Id` header**: ensure the request passed through Nginx at `/mcp` so the transport stays on streamable HTTP.
- **401 / tunnel login**: open VS Code tunnel logs from Streamlit onboarding to capture the authentication URL and code.
- **Session not visible**: check `/var/log/supervisor/vibestack-mcp.log`; ensure `VIBESTACK_HOME` points to `/home/vibe` and the service runs as the `vibe` user.
- **Clients still attempting SSE**: update their configuration to `type: "streamable-http"` and drop legacy `/sse` suffixes.

## Related Files
- Server implementation: `vibestack/mcp/server.py`
- Connectivity helper: `examples/mcp_runner.py`
- Architecture notes: `docs/mcp-session-integration.md`
