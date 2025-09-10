#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="vibestack"

if ! docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  echo "Container '${CONTAINER_NAME}' is not running. Start it with: ./scripts/start.sh" >&2
  exit 1
fi

echo "Executing codex login inside container..."
echo "You can pass extra flags/args, e.g. '--model gpt-4.1' or custom options per Codex advanced docs."

docker exec -it "${CONTAINER_NAME}" bash -lc "codex login $*"

echo "If Codex opened a callback on a local port, it's already mapped via CODEX_CALLBACK_PORT in ./scripts/start.sh."

