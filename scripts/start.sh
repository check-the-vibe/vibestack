#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="vibestack"
CONTAINER_NAME="vibestack"
ENV_FILE_FLAG=""
FOLLOW_LOGS=1
HOST_HTTP_PORT="3000"
HOST_PROJECTS_DIR=""

if [[ "${1:-}" == "--no-logs" ]]; then
  FOLLOW_LOGS=0
fi

if [ -f .env ]; then
  ENV_FILE_FLAG="--env-file .env"
fi

# Extract CODEX_CALLBACK_PORT from .env if present, else default to 1455
CODEX_CALLBACK_PORT="1455"
if [ -f .env ]; then
  # shellcheck disable=SC2046
  CODEX_CALLBACK_PORT=$(grep -E '^CODEX_CALLBACK_PORT=' .env | tail -1 | cut -d'=' -f2- || echo 1455)
  CODEX_CALLBACK_PORT=${CODEX_CALLBACK_PORT:-1455}
  # Extract HOST_HTTP_PORT from .env if present, else default to 3000
  HOST_HTTP_PORT=$(grep -E '^HOST_HTTP_PORT=' .env | tail -1 | cut -d'=' -f2- || echo 3000)
  HOST_HTTP_PORT=${HOST_HTTP_PORT:-3000}
  # Optional: host projects directory to mount at /projects
  HOST_PROJECTS_DIR=$(grep -E '^HOST_PROJECTS_DIR=' .env | tail -1 | cut -d'=' -f2- || true)
fi

# Default HOST_PROJECTS_DIR to $HOME/Projects if unset
if [ -z "$HOST_PROJECTS_DIR" ]; then
  HOST_PROJECTS_DIR="$HOME/Projects"
fi

# Ensure the host projects directory exists so the bind mount works
if [ ! -d "$HOST_PROJECTS_DIR" ]; then
  echo "[vibestack] Creating host projects directory: $HOST_PROJECTS_DIR"
  mkdir -p "$HOST_PROJECTS_DIR"
fi

echo "[vibestack] Building image: ${IMAGE_NAME}"
docker build -t "${IMAGE_NAME}" .

if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  echo "[vibestack] Removing existing container: ${CONTAINER_NAME}"
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
fi

echo "[vibestack] Starting container: ${CONTAINER_NAME}"
docker run -d \
  --name "${CONTAINER_NAME}" \
  ${ENV_FILE_FLAG} \
  -e CODEX_CALLBACK_PORT="${CODEX_CALLBACK_PORT}" \
  -v "${HOST_PROJECTS_DIR}:/projects" \
  -p ${HOST_HTTP_PORT}:80 \
  -p 2222:22 \
  -p 7681:7681 \
  -p 8501:8501 \
  -p ${CODEX_CALLBACK_PORT}:1456 \
  "${IMAGE_NAME}"

echo "[vibestack] Ready. Access points:"
echo "  - Web Terminal (tmux):   http://localhost:${HOST_HTTP_PORT}/"
echo "  - Streamlit UI:          http://localhost:${HOST_HTTP_PORT}/ui/"
echo "  - SSH:                   ssh vibe@localhost -p 2222 (password from .env or 'coding')"
echo "  - Direct ttyd:           http://localhost:7681/"
echo "  - Direct Streamlit:      http://localhost:8501/"
echo "  - Codex callback port:   host:${CODEX_CALLBACK_PORT} -> container:1456 -> 127.0.0.1:${CODEX_CALLBACK_PORT}"
echo "  - Host Projects mapped:  ${HOST_PROJECTS_DIR} -> /projects"
echo ""
echo "Codex login tips:"
echo "  - Inside terminal: run 'codex login' (add flags as needed)"
echo "  - Or run: ./scripts/codex-login.sh [args...]"
echo "  - Ensure callback port ${CODEX_CALLBACK_PORT} is mapped (done above)"

if [[ "$FOLLOW_LOGS" -eq 1 ]]; then
  echo ""
  echo "[vibestack] Following container logs (Ctrl+C to stop following; container keeps running)"
  trap 'echo; echo "[vibestack] Log follow stopped."' INT TERM
  docker logs -f --since=1s "${CONTAINER_NAME}"
fi
