# Visual Studio Code Tunnel

## Purpose
Expose a `code tunnel` endpoint so agents can connect with the Visual Studio Code desktop client without opening new network ports. The service keeps the tunnel online under Supervisor and uses the upstream VS Code CLI binaries.

## Startup & Lifecycle
- Supervisor program: `vscode-tunnel`.
- Command: `/home/vibe/bin/vibestack-code-tunnel` (runs `code tunnel --accept-server-license-terms`).
- User: `vibe` with CLI data rooted at `/home/vibe/.vscode-cli` to persist authentication and settings.
- Logs: `/var/log/supervisor/vscode-tunnel.log` for both stdout and stderr.

## Authentication Flow
1. Tail the log (prefer `python -m vibestack.scripts.supervisor_helper tail -f vscode-tunnel`) after the service starts.
2. On first launch the CLI prints a `https://microsoft.com/devicelogin` URL plus a code—open it in a browser and authenticate with the Microsoft account that should own the tunnel.
3. The CLI stores credentials in `/home/vibe/.vscode-cli` so subsequent restarts reuse the session. If you need to sign out, remove that directory and restart the program.

## Configuration Knobs
- `VSCODE_TUNNEL_NAME` – override the advertised tunnel name (default: `vibestack`).
- `VSCODE_TUNNEL_EXTRA_ARGS` – append extra CLI flags, e.g. `"--log trace"` or `"--allow-untrusted"`.
- `VSCODE_CLI_DATA_DIR` / `VSCODE_CLI_LOG_DIR` – point the CLI at alternate persistence or logging folders.
- `CODE_BIN` – use a different VS Code CLI binary location if needed (defaults to `/usr/local/bin/code`).

Update the Supervisor program environment or export the variables before launching the helper script to change these values.

## Troubleshooting
- **Tunnel repeatedly restarts** → check the log for authentication prompts; the CLI exits after printing sign-in instructions until the device code flow is completed.
- **VS Code client cannot connect** → confirm the tunnel appears under `code tunnel status` locally and that internet egress is allowed from the container.
- **Binary missing** → rebuild the image so the Dockerfile downloads the VS Code CLI bundle into `/opt/vscode-cli`.
