# ttyd Web Terminal

## Purpose
Provides a browser-based terminal with tmux integration so agents can work inside the container without SSH. Backed by `ttyd`, which bridges WebSockets to a local shell.

## Startup & Lifecycle
- Supervisor program: `ttyd`.
- Command: `/usr/bin/ttyd -p 7681 --writable --url-arg -t disableResizeOverlay=1 -t disableLeaveAlert=1 -t titleFixed=VibeStack --cwd /home/vibe /usr/local/bin/vibestack-ttyd-entry`.
- Runs as `vibe` with `PYTHONPATH` pointing at `/home/vibe`.
- Logs: `/var/log/ttyd.log` (stdout) and `/var/log/ttyd.err` (stderr).

## Routing & Access
- Internal port: `7681`.
- Nginx proxy:
  - `/terminal/` → primary terminal UI.
  - `/` (fallback) → also points at ttyd so the root path drops you in the shell.

## Entry Script (`vibestack-ttyd-entry`)
- Default action: launches an interactive login shell.
- `session <name>`: attach to an existing tmux/VibeStack session.
- `create [template] [name]`: create a new session via `vibestack-sessions` CLI and attach immediately.
- `oneoff [template] [name] <command>`: queue a one-off job and follow its tmux output.
- Any other argument is treated as a session name to attach to.

## Common Tasks
- **Attach to session:** open `/terminal/` and run `vibestack-ttyd-entry session <name>`.
- **List sessions:** `vibestack-sessions list`.
- **Run custom command:** `vibestack-ttyd-entry oneoff script job-foo "pytest -q"`.

## Troubleshooting
- Blank page → check `/var/log/ttyd.err` and ensure nothing else is bound to port 7681.
- Session not found errors → verify the session exists with `tmux list-sessions`.
- Keyboard layout quirks → adjust ttyd launch flags or rely on SSH (`sshd` service) if your workflow needs native terminal support.
