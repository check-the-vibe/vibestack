#!/usr/bin/env bash
set -euo pipefail

# Lightweight Chrome/Chromium launcher for container use
# Adds no-sandbox flags and a persistent user data dir.

# Pick the first available Chrome/Chromium binary
BIN=""
for c in google-chrome-stable google-chrome chromium chromium-browser; do
  if command -v "$c" >/dev/null 2>&1; then BIN="$c"; break; fi
done

if [ -z "$BIN" ]; then
  echo "Chrome/Chromium not found. Try: npx -y playwright install chrome" >&2
  exit 1
fi

DATA_DIR="${CHROME_USER_DATA_DIR:-$HOME/.config/google-chrome}"
mkdir -p "$DATA_DIR"

FLAGS=(
  --no-sandbox
  --disable-setuid-sandbox
  --disable-dev-shm-usage
  --no-first-run
  --user-data-dir="$DATA_DIR"
  --password-store=basic
  --use-mock-keychain
)

exec "$BIN" "${FLAGS[@]}" "$@"
