#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="vibestack-current"
CONTAINER_NAME="vibestack-current-dev"
PLATFORM="linux/amd64"
PROJECTS_MOUNT="/Users/neal/Projects:/projects"
CODEX_STATE_HOST="/Users/neal/Projects/codex-state"
CODEX_STATE_MOUNT="${CODEX_STATE_HOST}:/data/codex"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "$0")"

FOLLOW_LOGS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    follow)
      FOLLOW_LOGS=true
      shift
      ;;
    *)
      echo "[startup] Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

build_image() {
  echo "[startup] Building ${IMAGE_NAME} for ${PLATFORM}..."
  docker buildx build \
    --platform "${PLATFORM}" \
    -t "${IMAGE_NAME}" \
    "${SCRIPT_DIR}" \
    --load
}

stop_existing_container() {
  if docker ps -a --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
    echo "[startup] Removing existing container ${CONTAINER_NAME}..."
    docker rm -f "${CONTAINER_NAME}" >/dev/null
  fi
}

start_container() {
  echo "[startup] Starting ${CONTAINER_NAME} in detached mode..."
  docker run -d \
    --name "${CONTAINER_NAME}" \
    --platform "${PLATFORM}" \
    -p 3000:80 \
    -p 1455:1456 \
    -v "${PROJECTS_MOUNT}" \
    -v "${CODEX_STATE_MOUNT}" \
    -e CODEX_STATE_DIR=/data/codex \
    "${IMAGE_NAME}"
}

tail_logs() {
  echo "[startup] Tailing logs for ${CONTAINER_NAME} (Ctrl+C to stop)..."
  docker logs -f "${CONTAINER_NAME}"
}

build_image
stop_existing_container
start_container

if [[ "${FOLLOW_LOGS}" == "true" ]]; then
  tail_logs
else
  echo "[startup] Container started. Run ./${SCRIPT_NAME} follow to stream logs."
fi
