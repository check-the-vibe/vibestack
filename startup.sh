#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="vibestack-current"
CONTAINER_NAME="vibestack-current-dev"
PLATFORM="linux/amd64"
PROJECTS_MOUNT="/Users/neal/Projects:/projects" # default; override with --projects <path>
CODEX_STATE_HOST="/Users/neal/Projects/codex-state"
CODEX_STATE_MOUNT="${CODEX_STATE_HOST}:/data/codex"
# Reserve a minimum memory footprint unless overridden by env.
MEMORY_RESERVATION="${MEMORY_RESERVATION:-4g}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "$0")"

FOLLOW_LOGS=false
VALIDATE=false
BASE_URL="${VIBESTACK_BASE_URL:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    follow)
      FOLLOW_LOGS=true
      shift
      ;;
    validate)
      VALIDATE=true
      shift
      ;;
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --base-url=*)
      BASE_URL="${1#*=}"
      shift
      ;;
    --projects)
      PROJECTS_ARG="$2"
      shift 2
      ;;
    --projects=*)
      PROJECTS_ARG="${1#*=}"
      shift
      ;;
    *)
      echo "[startup] Unknown argument: $1" >&2
      echo "Usage: $SCRIPT_NAME [follow|validate] [--base-url=<url>] [--projects=<host-path>]" >&2
  echo "  follow         - tail logs after starting" >&2
  echo "  validate       - run validation checks and exit" >&2
  echo "  --base-url     - set public base URL (e.g., https://example.ngrok.app)" >&2
  echo "  --projects     - host folder to mount at /projects (relative/tilde ok)" >&2
  exit 1
  ;;

  esac
done

detect_ngrok_url() {
  local port="${1:-3000}"
  
  if ! command -v jq &> /dev/null; then
    return 1
  fi
  
  if ! command -v curl &> /dev/null; then
    return 1
  fi
  
  local ngrok_api="http://127.0.0.1:4040/api/tunnels"
  local response
  response=$(curl -s --connect-timeout 2 "${ngrok_api}" 2>/dev/null) || return 1
  
  if [[ -z "${response}" ]]; then
    return 1
  fi
  
  local url
  url=$(echo "${response}" | jq -r --arg port "${port}" '.tunnels[] | select(.config.addr | contains(":" + $port)) | .public_url' 2>/dev/null | grep '^https://' | head -1)
  
  if [[ -n "${url}" ]]; then
    echo "${url}"
    return 0
  fi
  
  return 1
}

if [[ -z "${BASE_URL}" ]]; then
  echo "[startup] No base URL provided, attempting to detect ngrok tunnel..."
  DETECTED_URL=$(detect_ngrok_url 3000)
  if [[ -n "${DETECTED_URL}" ]]; then
    BASE_URL="${DETECTED_URL}"
    echo "[startup] ✓ Detected ngrok URL: ${BASE_URL}"
  else
    echo "[startup] ⚠ Could not detect ngrok tunnel (is ngrok running for port 3000?)"
    echo "[startup] Continuing without base URL. Services will use defaults."
  fi
fi

# Resolve path to absolute (supports ~ and relative)
resolve_path() {
  local input_path="$1"
  # Expand tilde
  if [[ "$input_path" == ~* ]]; then
    input_path="${input_path/#~/$HOME}"
  fi
  # If not absolute, prefix with current working directory
  if [[ "$input_path" != /* ]]; then
    input_path="$(pwd)/$input_path"
  fi
  # Canonicalize if realpath exists
  if command -v realpath >/dev/null 2>&1; then
    realpath -m "$input_path"
  else
    echo "$input_path"
  fi
}

# If user provided --projects, update PROJECTS_MOUNT accordingly
if [[ -n "${PROJECTS_ARG:-}" ]]; then
  HOST_PROJECTS_DIR="$(resolve_path "${PROJECTS_ARG}")"
  PROJECTS_MOUNT="${HOST_PROJECTS_DIR}:/projects"
  echo "[startup] Using host projects dir: ${HOST_PROJECTS_DIR} -> /projects"
fi

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
  
  local docker_args=(
    -d
    --name "${CONTAINER_NAME}"
    --platform "${PLATFORM}"
    --security-opt seccomp=unconfined
    --memory-reservation "${MEMORY_RESERVATION}"
    --gpus=all
    -p 3000:80
    -p 1455:1456
    -v "${PROJECTS_MOUNT}"
    -v "${CODEX_STATE_MOUNT}"
    -e CODEX_STATE_DIR=/data/codex
  )
  
  if [[ -n "${BASE_URL}" ]]; then
    echo "[startup] Setting VIBESTACK_PUBLIC_BASE_URL=${BASE_URL}"
    docker_args+=(-e "VIBESTACK_PUBLIC_BASE_URL=${BASE_URL}")
  fi
  
  docker run "${docker_args[@]}" "${IMAGE_NAME}"
}

run_validations() {
  echo "[validate] Running host-level validations against http://localhost:3000"
  failures=0

  # /admin/docs should be 200 HTML
  status_ct=$(curl -sS -o /dev/null -w "HTTP:%{http_code} CT:%{content_type}" http://localhost:3000/admin/docs || true)
  echo "[validate] /admin/docs => ${status_ct}"
  [[ "$status_ct" == HTTP:200* ]] || { echo "[validate][fail] /admin/docs"; failures=$((failures+1)); }

  # /admin/api/sessions should be 200 JSON and contain schema_version
  body=$(curl -sS http://localhost:3000/admin/api/sessions || true)
  echo "[validate] /admin/api/sessions sample: $(echo "$body" | head -c 200)"; echo
  echo "$body" | jq . >/dev/null 2>&1 && echo "[validate] JSON parse: ok" || { echo "[validate][fail] JSON parse"; failures=$((failures+1)); }

  code=$(curl -sS -o /dev/null -w "%{http_code}" http://localhost:3000/admin/api/sessions || true)
  echo "[validate] /admin/api/sessions => HTTP:${code}"
  [[ "$code" == 200 ]] || { echo "[validate][fail] /admin/api/sessions"; failures=$((failures+1)); }

  # /mcp should return 406 unless Accept: text/event-stream is set
  mcp_headers=$(curl -sS -i http://localhost:3000/mcp | head -n 5 || true)
  echo "[validate] /mcp headers:\n${mcp_headers}"
  echo "$mcp_headers" | grep -q " 406 " || { echo "[validate][fail] /mcp expected 406"; failures=$((failures+1)); }

  mcp_sse=$(curl -sS -o /dev/null -w "%{http_code}" -H "Accept: text/event-stream" http://localhost:3000/mcp || true)
  echo "[validate] /mcp with SSE Accept => HTTP:${mcp_sse}"
  [[ "$mcp_sse" == 200 || "$mcp_sse" == 101 ]] || echo "[validate][warn] SSE status non-200 may be expected"

  if [[ $failures -eq 0 ]]; then
    echo "[validate] All checks passed"
    return 0
  else
    echo "[validate] ${failures} checks failed"
    return 1
  fi
}

tail_logs() {
  echo "[startup] Tailing logs for ${CONTAINER_NAME} (Ctrl+C to stop)..."
  docker logs -f "${CONTAINER_NAME}"
}

build_image
stop_existing_container
start_container

if [[ "${VALIDATE}" == "true" ]]; then
  # Wait briefly for services to boot
  echo "[startup] Waiting for services to start..."
  for i in {1..30}; do
    code=$(curl -sS -o /dev/null -w "%{http_code}" http://localhost:3000/admin/docs || true)
    if [[ "$code" == 200 ]]; then
      break
    fi
    sleep 1
  done
  run_validations
  exit_code=$?
  echo "[startup] Validation complete with exit code ${exit_code}"
  exit ${exit_code}
fi

if [[ "${FOLLOW_LOGS}" == "true" ]]; then
  tail_logs
else
  echo "[startup] Container started. Run ./${SCRIPT_NAME} follow to stream logs or 'validate' to run checks."
fi
