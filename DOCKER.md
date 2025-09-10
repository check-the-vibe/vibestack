# Container Architecture

## Overview
- Base: `ubuntu:22.04` with Streamlit UI and a web terminal (ttyd + tmux).
- Services (via `supervisord`):
  - `ttyd` on `:7681` (web terminal using tmux), proxied at `/` and `/terminal/` by Nginx.
  - `streamlit` UI on `:8501`, proxied at `/ui/` by Nginx.
  - `nginx` reverse proxy on `:80` and `sshd` for optional SSH.
  - Optional: Codex CLI available inside container (`@openai/codex`).

## Dockerfile Highlights
- System packages: Python 3, Node.js (LTS), tmux, CLI tools, SSH; no VNC/desktop, no browsers.
- Tools: `ttyd` (downloaded static), `@openai/codex` installed globally.
- Python: `llm`, `streamlit`, `openai` without cache.
- Users: creates `vibe` user (uid 1000) with passwordless sudo; passwords set at runtime in `entrypoint.sh`.
- Healthcheck: hits Streamlit via Nginx at `/ui/`.

## Nginx Routing
- `/` → ttyd (+tmux) (`:7681`).
- `/terminal/` → ttyd (+tmux) (`:7681`).
- `/ui/` → Streamlit (`:8501/`).

## Build & Run
- Easiest: `./scripts/start.sh` (maps 80, 2222->22, the Codex callback port from `.env` or default 1455, and mounts your host Projects folder to `/projects`).
- Manual: `docker build -t vibestack . && docker run -p 80:80 -p 2222:22 -p 3080:3080 -v "$HOME/Projects:/projects" vibestack`.
- Access:
  - Terminal (tmux): `http://localhost/` or `http://localhost/terminal/`
  - Streamlit UI: `http://localhost/ui/`
  - SSH: `ssh vibe@localhost -p 2222`
  
### Tmux Sessions via URL
- Default session: open `/` or `/terminal/` (attaches/creates session `main`).
- Named session: set the first `arg` to the session name, e.g. `http://localhost/terminal/?arg=projectA`.
- Run Codex on create: provide additional `arg` parameters after the session name; these are forwarded to the `codex` CLI only when the session is created. Examples:
  - `http://localhost/terminal/?arg=projA&arg=Build%20a%20hello%20world%20server`
  - `http://localhost/terminal/?arg=projB&arg=--model&arg=gpt-4.1&arg=Create%20a%20CLI%20parser`
  - Behavior: if `projA` does not exist, a new tmux session runs `codex "Build a hello world server"` then drops to a shell; subsequent attaches just attach without re-running codex.
  - Login example: `http://localhost/terminal/?arg=main&arg=login` (runs `codex login` on first creation)

## Environment & Config
- Env vars: `ROOT_PASSWORD`, `VIBE_PASSWORD`, `CODEX_CALLBACK_PORT` (default `1455`).
- Optional: `HOST_PROJECTS_DIR` to override host path mounted at `/projects` (default `$HOME/Projects`).
- DevContainer: `.devcontainer/devcontainer.json` builds with this Dockerfile and forwards port 80.
- Runtime docs: `.vibe/` contains `TASKS.md`, `ERRORS.md`, `LOG.txt`, `PERSONA.md` used by the UI.

## Notable Changes
- Removed VNC/desktop and browser installs (Firefox/Chrome, Playwright MCP).
- Ttyd now launches tmux by default, with session name taken from `?arg=<name>`.
- Codex CLI installed; expose `CODEX_CALLBACK_PORT` for login flows if needed. Nginx listens on port 1456 internally and proxies to `127.0.0.1:$CODEX_CALLBACK_PORT` so that host `:$CODEX_CALLBACK_PORT` works even if Codex binds to loopback.
