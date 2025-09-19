# Research: Short-Run Session Execution

Goal: ensure one-off jobs execute deterministically, terminate their tmux shell, and surface exit codes/output.

## Current behaviour
- `SessionManager.enqueue_one_off` delegates to `create_session(..., SessionType.ONE_OFF)`.
- `_launch_session` always spawns a detached tmux session running `bash --login` and injects commands via `send-keys`.
- For one-off jobs we append `; EXIT_CODE=$?; echo "[vibestack] session exited with code $EXIT_CODE" >> console.log; exit $EXIT_CODE`.
- Consequences:
  - Works, but relies on `send-keys` (prone to race conditions if shell prompt not ready).
  - Exit code only written to log; `SessionMetadata.exit_code` remains `None`.
  - tmux session may linger briefly if shell startup scripts prompt for input.

## Candidate approaches

### 1. Direct tmux command
- Run `tmux new-session -d -s <name> "bash -lc '<command>; EXIT=$?; ...; exit $EXIT'"`.
- Pros: no `send-keys` race; shell lifecycle tied to command.
- Cons: handling working directory/env injection requires building a single shell string.

### 2. `tmux respawn-pane`
- Create base session with login shell, then use `respawn-pane -k` to run one-off command. Pane exits automatically and session dies.
- Still involves readiness checks.

### 3. `tmux run-shell`
- `tmux run-shell` executes command without creating session; output can be piped but not attached to a shared log easily.
- Not ideal if we want to stream logs via ttyd.

### 4. Wrapper script
- Generate `/home/vibe/bin/vibestack-run-once` that wraps command, writes status JSON, and exits. tmux session runs this script directly.

## Exit-code capture
- After command exits, we can read `$?` inside the wrapper and write both log line and a structured file (e.g., `<workspace>/result.json`) for quick lookup.
- `SessionManager._refresh_status` can parse this file and update `metadata.exit_code` + `metadata.last_message`.

## Proposed direction
1. For short-run jobs, avoid `send-keys`: start tmux session with `bash -lc` executing the wrapper script.
2. Wrapper should handle working directory, env injection, log append, and writing a `result.json` (exit code, start/end timestamps, final stdout snippet).
3. On completion, `_refresh_status` reads result file if present, updates metadata, and ensures session marked completed/failed accordingly.

Open questions:
- Should short-run jobs still create a tmux session for streaming (so ttyd can follow)? → yes, keep for parity; wrapper script can tee output to log.
- How to surface final output efficiently? → Milestone 3 will add API/CLI to read `result.json` or tail `console.log`.
- Handling long commands with quotes/newlines: need robust escaping (use `shlex.quote` and a here-doc in wrapper).
