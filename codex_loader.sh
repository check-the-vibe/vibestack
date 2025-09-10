#!/usr/bin/env bash
set -euo pipefail

# Forward all args to the Codex CLI; when it exits, fall back to a shell
# This allows passing prompts and flags straight from ttyd query params.

if command -v codex >/dev/null 2>&1; then
  codex "$@" || true
else
  echo "codex CLI not found on PATH. Starting a shell instead." >&2
fi

exec bash -l
