#!/usr/bin/env bash
set -euo pipefail

# tmux session wrapper for ttyd
# Query param handling (ttyd --url-arg):
#   /terminal/                       -> session "main"
#   /terminal/?arg=NAME              -> session NAME
#   /terminal/?arg=NAME&arg=...      -> session NAME, remaining args handled

SESSION_NAME="${1:-main}"
shift || true

# Remaining args (if any)
EXTRA_ARGS=("$@")

# Attach if session exists; if args provided, send them before attaching
if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
  if [ ${#EXTRA_ARGS[@]} -gt 0 ]; then
    payload=""
    for a in "${EXTRA_ARGS[@]}"; do
      if [ -n "${payload}" ]; then payload+=" "; fi
      payload+="${a}"
    done
    # Send the payload first, then a standard Enter
    # Note: tmux/xterm do not provide a distinct Shift+Enter keycode
    # in a portable way; attempting to send "S-Enter" types the string.
    tmux send-keys -t "${SESSION_NAME}" -- "${payload}"
    tmux send-keys -t "${SESSION_NAME}" Enter
  fi
  exec tmux attach -t "${SESSION_NAME}"
fi

# Create new session
if [ ${#EXTRA_ARGS[@]} -eq 0 ]; then
  # No args: start an interactive shell
  tmux new-session -s "${SESSION_NAME}" -d
else
  # Args provided on first create: forward to codex loader, then drop to shell
  tmux new-session -s "${SESSION_NAME}" -d \
    "/usr/local/bin/codex_loader.sh" "${EXTRA_ARGS[@]}"
fi

exec tmux attach -t "${SESSION_NAME}"
