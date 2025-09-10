#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="vibestack"
ACTION="${1:-help}"
TARGET="${2:-}" # session:window.pane (tmux target format), or session name
shift 2 || true

case "$ACTION" in
  ls)
    docker exec -it "$CONTAINER_NAME" tmux ls || true
    ;;
  info)
    if [ -z "$TARGET" ]; then echo "Usage: $0 info <session>"; exit 2; fi
    docker exec -it "$CONTAINER_NAME" bash -lc "tmux list-windows -t '$TARGET'; tmux list-panes -a -F '#S:#I.#P #{pane_active} #{pane_title}'"
    ;;
  attach)
    if [ -z "$TARGET" ]; then echo "Usage: $0 attach <session>"; exit 2; fi
    docker exec -it "$CONTAINER_NAME" tmux attach -t "$TARGET"
    ;;
  send)
    # Usage: send <target> <keys...>  (example: send main C-c "echo hi" Enter)
    if [ -z "$TARGET" ]; then echo "Usage: $0 send <target> <keys...>"; exit 2; fi
    docker exec -it "$CONTAINER_NAME" tmux send-keys -t "$TARGET" "$@"
    ;;
  capture)
    # Usage: capture <target>
    if [ -z "$TARGET" ]; then echo "Usage: $0 capture <target>"; exit 2; fi
    docker exec -it "$CONTAINER_NAME" tmux capture-pane -p -t "$TARGET"
    ;;
  help|*)
    cat <<EOF
tmux tools (inside container: $CONTAINER_NAME)

Usage:
  $0 ls                        # list sessions
  $0 info <session>            # windows/panes summary
  $0 attach <session>          # attach into a session
  $0 send <target> <keys...>   # send keys (e.g., C-c, Enter, strings)
  $0 capture <target>          # print pane contents

Targets use tmux syntax: <session> or <session>:<window>.<pane>
EOF
    ;;
esac
