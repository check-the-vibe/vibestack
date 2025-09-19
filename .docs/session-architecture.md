# Session Architecture

This document captures how session orchestration works in `vibestack-current` and the surfaces that sit on top of it.

## Filesystem layout
- Root: `/home/vibe/sessions`
- For each session `<name>` we create:
  - `/home/vibe/sessions/<name>/metadata.json`
    - Serialized `SessionMetadata`, includes command, template, type (long_running/one_off), timestamps, log/workspace pointers, job id.
  - `/home/vibe/sessions/<name>/console.log`
    - Output captured from the primary tmux pane via `pipe-pane`.
  - `/home/vibe/sessions/<name>/artifacts/`
    - Workspace for one-off outputs or manual file drops; exposed in Streamlit.
- Queue file: `/home/vibe/sessions/queue.json`
  - Append-only job log with `id`, `session`, `status`, timestamps, optional message. Updated whenever `SessionStorage.update_job_status` is invoked.

## Python package (`vibestack.sessions`)
- `SessionManager`
  - Constructor accepts `session_root` override (default via `VIBESTACK_SESSION_ROOT` env or `/home/vibe/sessions`).
  - `DEFAULT_TEMPLATES`: `bash`, `claude`, `codex`, `script`; each maps to a command and default `SessionType`.
  - `create_session` → bootstraps tmux session, pipes logs, records job entry, updates metadata.
  - `enqueue_one_off` → wrapper forcing `SessionType.ONE_OFF`.
  - `send_text`, `kill_session`, `tail_log` for stream control.
  - `_launch_session` ensures tmux session exists, enables `pipe-pane`, optionally `cd`s into `working_dir`, and wraps one-off commands with exit logging.
- `SessionMetadata`
  - Dataclass with `schema_version=1`; `ensure_paths()` enforces directories.
- `SessionStorage`
  - Lookup helpers (`list_sessions`, `load`, `delete`).
  - Job queue helpers (`add_job`, `update_job_status`, `list_jobs`).

## CLI wrappers (`bin/vibestack-sessions`)
- Delegates to `python3 -m vibestack.sessions.cli` while injecting `PYTHONPATH`.
- Subcommands:
  - `list`, `show <name>`
  - `create <name> [--template ...] [--command ...]`
  - `one-off <name> <command>`
  - `send <name> <text> [--no-enter]`
  - `kill <name>`
  - `logs <name> [--lines N]`
  - `jobs`
- Designed to run both on host (with `VIBESTACK_HOME` override) and in container.

## ttyd bridge (`bin/vibestack-ttyd-entry`)
- Parses URL args forwarded by ttyd’s `--url-arg` flag.
- Ensures session exists via the CLI, then attaches to tmux.
- Supported actions:
  - default / no arg → `workspace` session (template `bash`).
  - `session <name> [template]` → attach.
  - `create <template> [name]` → create and attach.
  - `oneoff <template> <name> <command>` → queue command, attach to follow output.

## Streamlit integration
- New `app.py` builds the “Session Control Center”.
  - Sidebar creates long-running sessions and queues one-off jobs via `SessionManager`.
  - Main view tabs:
    - **Terminal**: iframe to `/terminal/` with `arg=session`/`arg=<name>`/`arg=<template>` (ttyd picks up and attaches).
    - **Logs**: tail of `console.log`.
    - **Workspace**: lists `artifacts/` directory.
    - **Streamlit**: inline editor for `/home/vibe/streamlit` sources for hot iteration.
  - Job queue table shows `queue.json` contents.
- Additional Streamlit pages:
  - `🗂️ Session Storage`: inspect metadata, download logs, kill sessions, browse artifacts.
  - `💻 Terminal`: single fullscreen terminal bound to selected session.
  - `📁 Workspace Explorer`: browses Streamlit source, package code, and sessions directory.

## Environment variables
- `VIBESTACK_HOME` → default `/home/vibe`; exported in entrypoint (sets `PYTHONPATH`).
- `VIBESTACK_SESSION_ROOT` (optional) → overrides session storage root.
- `CODEX_CALLBACK_PORT` (new) → default `1455`; used to render the Nginx upstream that proxies Codex login.
- `VIBESTACK_TTYD_BASE` (optional) → override iframe base URL (defaults to `/terminal/`).

## Services
- Supervisor launches tmux shell via ttyd, Streamlit, nginx, VNC stack, playwright MCP.
- Nginx updates:
  - `/terminal/` for ttyd.
  - `/codex-callback/` path for Codex login callback.
  - Dedicated server on `1456` bridging host callback port to Codex loopback listener.

## Persistence & cleanup
- Killing a session via CLI or Streamlit updates metadata status to `stopped`.
- One-off jobs auto-transition to `completed` once tmux session exits.
- `queue.json` retains history until manual pruning.
- Removing a session (`SessionStorage.delete`) deletes its directory tree.
