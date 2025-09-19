# Tmux Session Metadata Surfaces

This note summarizes the pieces of metadata tmux already exposes so we can surface them through the VibeStack session manager, REST API, and Streamlit UI. Everything below is available with stock tmux and requires no patches.

## Querying tmux for structured data
- `tmux list-sessions -F ...` returns one line per session, with each field rendered from a format string. Use it to retrieve core session information without parsing human-oriented output.
- `tmux list-clients`, `tmux list-windows`, and `tmux list-panes` accept the same `-F` flag and can be scoped with `-t` (target) so you can enumerate clients, windows, and panes for a specific session.
- `tmux display-message -p ...` prints a single formatted record. This is the quickest path to fetch individual attributes (for example `tmux display-message -t vibe:0.0 -p '#{pane_pid}'`).
- `tmux show-options -g|-s|-w` surfaces all server, session, or window options. Custom metadata can be persisted with `set-option -g @key value` and later read via `show-options -gqv @key`.
- `tmux show-environment [-g|-t session]` exposes the global and per-session environment scopes. Values can be updated with `set-environment` and are merged into the processes spawned for each pane.

When using the `-F` flag you can build structured payloads, for example:

```bash
# session_id,name,window_count,is_attached created_epoch
TMUX_FMT='#{session_id},#{session_name},#{session_windows},#{?session_attached,1,0} #{session_created}'
tmux list-sessions -F "$TMUX_FMT"
```

## High-value format fields
The tmux format language (see `man tmux`, *FORMATS*) exposes hundreds of variables. These are the most relevant for session orchestration:

| Format | Scope | Meaning |
| --- | --- | --- |
| `#{session_id}` | session | Unique session ID (`$TMUX` contains the same ID alongside socket and client PID).
| `#{session_name}` | session | Friendly name shown in status line and attach prompts.
| `#{session_created}` | session | Session creation time (Unix epoch).
| `#{session_last_attached}` | session | Epoch timestamp of the most recent attach.
| `#{session_attached}` / `#{session_many_attached}` | session | Flag indicating whether ≥1 clients are attached, and whether multiple clients share the session.
| `#{session_windows}` / `#{session_stack}` | session | Count of windows and most-recently-used window order.
| `#{session_path}` | session | Working directory inherited by new windows in the session.
| `#{session_width}` / `#{session_height}` | session | Size of the session when it last had an attached client.
| `#{client_pid}` / `#{client_tty}` | client | PID and TTY for each attached client, useful for correlating Streamlit UI tabs or ttyd connections.
| `#{client_width}` / `#{client_height}` | client | Last reported client size in cells.
| `#{client_last_activity}` | client | Epoch timestamp of the last input from the client.
| `#{window_id}` / `#{window_index}` / `#{window_name}` | window | Identity and label of each window.
| `#{window_layout}` | window | Encodes pane splits; handy when mirroring layout in the UI.
| `#{window_activity}` / `#{window_bell_flag}` / `#{window_silence_flag}` | window | Last-activity timestamps and alert flags per window.
| `#{pane_id}` / `#{pane_index}` | pane | Unique pane handle (also available to processes via `$TMUX_PANE`).
| `#{pane_pid}` / `#{pane_tty}` | pane | Process tree anchor and PTY for the pane.
| `#{pane_current_command}` / `#{pane_title}` / `#{pane_current_path}` | pane | What is running, the pane title, and the present working directory.
| `#{pane_width}` / `#{pane_height}` / `#{pane_in_mode}` | pane | Pane dimensions and whether it is in copy-mode or another specialized mode.
| `#{host}` / `#{user}` / `#{server_pid}` / `#{socket_path}` | server | Server-level metadata; useful for diagnostics and multi-host awareness.

Use these fields with the `-F` flag or inside `display-message` templates. `tmux list-*-F` outputs UTF-8 friendly strings that are easy to parse in Python.

## Environment variables inside tmux
When tmux launches a client it seeds two overlapping environments:
- **Global environment** – the snapshot taken when the server first starts.
- **Session environment** – a per-session overlay applied on top of the global environment when panes spawn processes.

Key variables tmux injects:
- `TMUX` – encoded as `socket_path,client_pid,session_id`. Presence of this variable is a reliable indicator that a process runs under tmux.
- `TMUX_PANE` – unique pane ID (for example `%3`). You can map this back to metadata using `tmux display-message -p -t "${TMUX_PANE}" ...`.
- `TERM` – overriden to `screen`, `screen-256color`, or another tmux-compatible terminfo entry.
- `TMUX_TMPDIR` – parent directory for tmux sockets when set (respects the environment inherited by the server).

Propagation controls:
- `update-environment` session option controls which variables tmux copies from the attaching client. The default list on this image is `DISPLAY`, `KRB5CCNAME`, `SSH_ASKPASS`, `SSH_AUTH_SOCK`, `SSH_AGENT_PID`, `SSH_CONNECTION`, `WINDOWID`, and `XAUTHORITY`.
- `tmux show-environment [-g|-t]` prints the effective environment; entries prefixed with `-` are marked for removal before child processes launch. Hidden variables (set with `set-environment -h`) remain available to tmux formats without leaking into child shells.

These hooks let the Python API expose SSH agent forwarding, DISPLAY availability, or other contextual signals alongside tmux metadata.

## Implementation notes for VibeStack
- The Python session manager can shell out to tmux with `subprocess.run(["tmux", "list-sessions", "-F", fmt])` to gather structured rows. Parsing CSV- or JSON-ready templates keeps code simple.
- Session-scoped metadata (for example, Streamlit project name or ticket number) can be stored with `tmux set-option -gq @project $VALUE` and retrieved through `tmux show-options -gqv @project`.
- Expose `TMUX_PANE`, `#{pane_pid}`, `#{pane_current_path}`, and `#{pane_current_command}` in the REST payload to help the UI surface process state per pane.
- Track `#{client_last_activity}`/`#{session_last_attached}` to implement idle detection and auto-suspend logic in the backend.
- Include the `update-environment` list (and any deviations we introduce) in API responses so callers understand which env vars survive into their workloads.

Documenting these fields gives us a concrete contract for synchronizing tmux state across the backend and UI without reverse-engineering tmux internals.
