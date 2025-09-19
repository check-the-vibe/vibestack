# Codex & Claude Authentication Notes

This file tracks what we know about CLI authentication flows and outstanding questions.

## Codex CLI
- Installed globally via `npm install -g @openai/codex` (see Dockerfile).
- Binary expects to bind an OAuth callback listener on `127.0.0.1:<port>` when running `codex login`.
- Default port: `CODEX_CALLBACK_PORT` (currently `1455`).
  - Entry `entrypoint.sh` emits `/etc/nginx/conf.d/codex_callback_upstream.conf` pointing to `127.0.0.1:$CODEX_CALLBACK_PORT`.
  - `nginx.conf` exposes:
    - Path proxy: `/codex-callback/` → `http://codex_callback/` (useful from within the container/Streamlit).
    - Dedicated server listener on container port `1456` that forwards to the upstream.
  - Docker run command should map host port 1455 to container 1456 (`-p 1455:1456`) so the host can hit `http://localhost:1455/...` during login.
- Login steps (tested):
  1. Attach to container shell as `vibe` user (`docker exec -it <id> su - vibe`).
  2. Run `codex login`.
  3. When prompted, visit the printed URL (`http://127.0.0.1:1455/auth/callback?...`).
  4. Host browser can reach this URL as long as `-p 1455:1456` is set.
  5. Tokens persist under `/home/vibe/.codex` (bind-mount if long-lived secrets desired).
- Open questions:
  - Confirm behaviour when multiple logins happen concurrently—do we need port randomisation?
  - Determine best practice for persisting `.codex` across container rebuilds (volume vs. host bind).
  - Document CLI-based API key login (`codex login --api-key`) as an alternative when callback flow is disabled.

## Claude CLI (`@anthropic-ai/claude-code`)
- Installed globally via `npm install -g @anthropic-ai/claude-code`.
- Current workflow: run `claude login` from a shell/tty; CLI handles the OAuth process in-terminal (no HTTP callback requirement).
- Credentials stored under `~/.claude`; consider binding `/home/vibe/.claude` if persistence required.
- Open questions:
  - Verify whether CLI supports environment-based auth (tokens) and document if so.
  - Determine how claude login interacts with tmux sessions launched via ttyd (do we need `login` wrapper?).

## Shared TODOs
- Publish a short FAQ covering "How do I authenticate Codex/Claude?" in README.
- Capture recommended volume mounts for credentials in future release doc.
