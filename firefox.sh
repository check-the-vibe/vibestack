#!/usr/bin/env bash
set -euo pipefail

# Simple Firefox launcher with isolated profile for container use
# Prefer the extracted binary path to avoid PATH recursion
if [ -x "/opt/firefox/firefox" ]; then
  BIN="/opt/firefox/firefox"
else
  BIN="$(command -v firefox || true)"
fi
if [ -z "$BIN" ]; then
  echo "Firefox not found."
  exit 1
fi

PROFILE_DIR="${FIREFOX_PROFILE_DIR:-$HOME/.mozilla/firefox-vibe}"
mkdir -p "$PROFILE_DIR"

# Ensure sandbox-disabling preferences are present in the profile
USER_JS="$PROFILE_DIR/user.js"
if [ ! -f "$USER_JS" ] || ! grep -q 'security.sandbox.content.level' "$USER_JS" 2>/dev/null; then
  {
    echo 'user_pref("security.sandbox.content.level", 0);'
    echo 'user_pref("security.sandbox.gpu.level", 0);'
    echo 'user_pref("security.sandbox.rdd.level", 0);'
    echo 'user_pref("security.sandbox.socket.process.level", 0);'
  } >> "$USER_JS"
fi

# Relax Firefox sandboxing for container use to avoid userns EPERM
export MOZ_DISABLE_CONTENT_SANDBOX=1
export MOZ_DISABLE_GMP_SANDBOX=1
export MOZ_DISABLE_RDD_SANDBOX=1
# Disable webrender to reduce GL requirements over virtual X
export MOZ_WEBRENDER=0

exec "$BIN" --no-remote --profile "$PROFILE_DIR" "$@"
