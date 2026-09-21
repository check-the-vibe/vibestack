#!/usr/bin/env bash
# Build the image and (re)start the container.
#
#   ./startup.sh                  build + run on 127.0.0.1:8080
#   ./startup.sh --port 9090      use a different host port
#   ./startup.sh --bind 0.0.0.0   explicitly expose it beyond this host
#   ./startup.sh --data DIR       persistent tool state (default: ../vibestack-data)
#   ./startup.sh --adopt-data      mark a safe pre-existing --data directory once
#   ./startup.sh --projects DIR   host folder for /projects (default: <data>/projects)
#   ./startup.sh --mount-source   also mount this checkout at /projects/<repo-name>
#   ./startup.sh --ssh-port 2222  publish SSH on host loopback (0 disables)
#   ./startup.sh --vnc-port 5900  publish password-authenticated native VNC (0 disables)
#   ./startup.sh --allowed-host NAME explicitly allow a custom browser hostname
#   ./startup.sh --flatpak        allow nested Flatpak application sandboxes
#   ./startup.sh --image TAG      build and run a named image tag
#   ./startup.sh --no-build       run an image that was already validated
#   VIBESTACK_RESTORE_TIMEOUT_SECONDS=3600  bound saved-component restoration
#   VIBESTACK_PIDS_LIMIT=1024        bounded task/thread capacity for GUI apps
#   ./startup.sh follow           tail logs after starting
#   ./startup.sh check            run the acceptance checks after starting
set -euo pipefail

IMAGE_NAME="${VIBESTACK_IMAGE:-vibestack}"
CONTAINER_NAME="${VIBESTACK_CONTAINER:-vibestack}"
PORT="${VIBESTACK_PORT:-8080}"
SSH_PORT="${VIBESTACK_SSH_PORT:-2222}"
NATIVE_VNC_HOST_PORT="${VIBESTACK_NATIVE_VNC_PORT:-5900}"
ALLOWED_HOSTS="${VIBESTACK_ALLOWED_HOSTS:-}"
BIND_ADDRESS="${VIBESTACK_BIND_ADDRESS:-127.0.0.1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DATA_DIR="${VIBESTACK_DATA:-${SCRIPT_DIR}/../vibestack-data}"
PROJECTS_DIR=""
MOUNT_SOURCE=false
FOLLOW=false
CHECK=false
SKIP_SETUP=false
[[ "${VIBESTACK_SKIP_SETUP:-}" == "1" ]] && SKIP_SETUP=true
BUILD=true
ADOPT_DATA=false
FLATPAK_MODE=false
[[ "${VIBESTACK_FLATPAK:-0}" == "1" ]] && FLATPAK_MODE=true
RESTORE_TIMEOUT_SECONDS="${VIBESTACK_RESTORE_TIMEOUT_SECONDS:-3600}"
PIDS_LIMIT="${VIBESTACK_PIDS_LIMIT:-1024}"

resolve() { realpath -m -- "${1/#\~/$HOME}"; }

# True when PATH is ROOT itself or a descendant on a path-component boundary.
# Both arguments are canonical absolute paths by the time this is called.
at_or_below() {
  local path="$1" root="$2"
  [[ "$path" == "$root" || "$path" == "$root/"* ]]
}

data_path_error() {
  echo "[startup] Unsafe data directory: $1" >&2
  exit 1
}

projects_path_error() {
  echo "[startup] Unsafe projects directory: $1" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    follow) FOLLOW=true; shift ;;
    check) CHECK=true; shift ;;
    --skip-setup) SKIP_SETUP=true; shift ;;
    --flatpak) FLATPAK_MODE=true; shift ;;
    --adopt-data) ADOPT_DATA=true; shift ;;
    --no-build) BUILD=false; shift ;;
    --mount-source) MOUNT_SOURCE=true; shift ;;
    --image) IMAGE_NAME="$2"; shift 2 ;;
    --image=*) IMAGE_NAME="${1#*=}"; shift ;;
    --name) CONTAINER_NAME="$2"; shift 2 ;;
    --name=*) CONTAINER_NAME="${1#*=}"; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --port=*) PORT="${1#*=}"; shift ;;
    --ssh-port) SSH_PORT="$2"; shift 2 ;;
    --ssh-port=*) SSH_PORT="${1#*=}"; shift ;;
    --vnc-port) NATIVE_VNC_HOST_PORT="$2"; shift 2 ;;
    --vnc-port=*) NATIVE_VNC_HOST_PORT="${1#*=}"; shift ;;
    --allowed-host) ALLOWED_HOSTS="$2"; shift 2 ;;
    --allowed-host=*) ALLOWED_HOSTS="${1#*=}"; shift ;;
    --bind) BIND_ADDRESS="$2"; shift 2 ;;
    --bind=*) BIND_ADDRESS="${1#*=}"; shift ;;
    --data) DATA_DIR="$2"; shift 2 ;;
    --data=*) DATA_DIR="${1#*=}"; shift ;;
    --projects) PROJECTS_DIR="$2"; shift 2 ;;
    --projects=*) PROJECTS_DIR="${1#*=}"; shift ;;
    *)
      echo "Usage: $(basename "$0") [follow|check] [--bind ADDRESS] [--port N] [--ssh-port N|0] [--vnc-port N|0] [--allowed-host NAME] [--data DIR] [--adopt-data] [--projects DIR] [--mount-source] [--image TAG] [--name NAME] [--no-build] [--skip-setup] [--flatpak]" >&2
      exit 1 ;;
  esac
done

DATA_DIR="$(resolve "$DATA_DIR")" || data_path_error "could not canonicalize path"
PROJECTS_DIR="$(resolve "${PROJECTS_DIR:-$DATA_DIR/projects}")" || \
  data_path_error "could not canonicalize projects path"
HOME_DIR="$(resolve "$HOME")" || data_path_error "could not canonicalize HOME"
SOURCE_NAME="${SCRIPT_DIR##*/}"
if [[ "$MOUNT_SOURCE" == true ]]; then
  [[ "$SOURCE_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$ && "$SCRIPT_DIR" != *,* ]] || \
    projects_path_error "source checkout path cannot be represented as a named Docker mount"
  source_target="$PROJECTS_DIR/$SOURCE_NAME"
  # A nested bind must never hide a user's existing project or follow a link.
  if [[ -L "$source_target" || ( -e "$source_target" && ! -d "$source_target" ) ]]; then
    projects_path_error "source mount destination is not a plain directory"
  fi
  if [[ -d "$source_target" && -n "$(find "$source_target" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    projects_path_error "source mount would hide an existing project"
  fi
fi

# /data is deliberately chowned/chmodded by the container's root bootstrap.
# Reject broad or source-containing bind mounts before creating anything or
# invoking Docker, including aliases normalized through symlinks and `..`.
[[ "$DATA_DIR" != "/" ]] || data_path_error "root is never a state directory"
case "$DATA_DIR" in
  /bin|/boot|/dev|/etc|/home|/lib|/lib32|/lib64|/media|/mnt|/opt|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var)
    data_path_error "system top-level directories are never state directories" ;;
esac
[[ "$DATA_DIR" != "$HOME_DIR" ]] || data_path_error "HOME is never a state directory"
[[ "$DATA_DIR" != "$PROJECTS_DIR" ]] || \
  data_path_error "state and projects directories must be different"
# Bootstrap changes the selected bind root's owner and mode. Never allow a
# descendant of an OS-owned hierarchy, even if --adopt-data is supplied.
for sensitive_root in \
  /bin /boot /dev /etc /lib /lib32 /lib64 /proc /root /run /sbin /sys /usr /var; do
  if at_or_below "$DATA_DIR" "$sensitive_root"; then
    data_path_error "state directory cannot be inside a system-owned hierarchy"
  fi
done
# Likewise keep credentials and source metadata outside the root bootstrap's
# reach. These checks are component-boundary based and run after realpath, so
# symlink and `..` aliases cannot bypass them.
for sensitive_root in \
  "$HOME_DIR/.ssh" "$HOME_DIR/.gnupg" "$HOME_DIR/.aws" \
  "$HOME_DIR/.azure" "$HOME_DIR/.docker" "$HOME_DIR/.kube" \
  "$HOME_DIR/.config/gcloud" "$HOME_DIR/.local/share/keyrings" \
  "$HOME_DIR/.password-store" "$HOME_DIR/.netrc"; do
  if at_or_below "$DATA_DIR" "$sensitive_root" || \
     at_or_below "$sensitive_root" "$DATA_DIR"; then
    data_path_error "state directory cannot contain credential state"
  fi
done
if [[ "$DATA_DIR" == "$HOME_DIR/.git"* ]]; then
  data_path_error "state directory cannot contain Git credential or metadata state"
fi
if at_or_below "$SCRIPT_DIR" "$DATA_DIR" || \
   at_or_below "$DATA_DIR" "$SCRIPT_DIR"; then
  data_path_error "state directory cannot overlap the VibeStack source tree"
fi
[[ "$PROJECTS_DIR" != "/" ]] || projects_path_error "root is never a projects directory"
case "$PROJECTS_DIR" in
  /bin|/boot|/dev|/etc|/home|/lib|/lib32|/lib64|/media|/mnt|/opt|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var)
    projects_path_error "system top-level directories are never projects directories" ;;
esac
[[ "$PROJECTS_DIR" != "$HOME_DIR" ]] || \
  projects_path_error "HOME is never a projects directory"
[[ "$PROJECTS_DIR" != "$SCRIPT_DIR" ]] || \
  projects_path_error "the VibeStack source tree is never a projects directory"
# /projects is writable from the browser desktop. Keep OS state, credentials,
# and repository metadata out even though this mount is not chowned at boot.
for sensitive_root in \
  /bin /boot /dev /etc /lib /lib32 /lib64 /proc /root /run /sbin /sys /usr /var; do
  if at_or_below "$PROJECTS_DIR" "$sensitive_root"; then
    projects_path_error "projects directory cannot be inside a system-owned hierarchy"
  fi
done
for sensitive_root in \
  "$HOME_DIR/.ssh" "$HOME_DIR/.gnupg" "$HOME_DIR/.aws" \
  "$HOME_DIR/.azure" "$HOME_DIR/.docker" "$HOME_DIR/.kube" \
  "$HOME_DIR/.config/gcloud" "$HOME_DIR/.local/share/keyrings" \
  "$HOME_DIR/.password-store" "$HOME_DIR/.netrc"; do
  if at_or_below "$PROJECTS_DIR" "$sensitive_root" || \
     at_or_below "$sensitive_root" "$PROJECTS_DIR"; then
    projects_path_error "projects directory cannot contain credential state"
  fi
done
if [[ "$PROJECTS_DIR" == */.git || "$PROJECTS_DIR" == */.git/* ]] || \
   [[ "$PROJECTS_DIR" == "$HOME_DIR/.git"* ]]; then
  projects_path_error "projects directory cannot be Git credential or metadata state"
fi

if [[ ! "$PORT" =~ ^[0-9]{1,5}$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "[startup] Invalid port: ${PORT}" >&2
  exit 1
fi
for optional_port in "$SSH_PORT" "$NATIVE_VNC_HOST_PORT"; do
  if [[ ! "$optional_port" =~ ^[0-9]{1,5}$ ]] || (( optional_port < 0 || optional_port > 65535 )); then
    echo "[startup] Invalid optional host port: ${optional_port}" >&2
    exit 1
  fi
done
if (( SSH_PORT != 0 && (SSH_PORT == PORT || SSH_PORT == NATIVE_VNC_HOST_PORT) )) || \
   (( NATIVE_VNC_HOST_PORT != 0 && NATIVE_VNC_HOST_PORT == PORT )); then
  echo "[startup] HTTP, SSH, and native VNC host ports must be distinct." >&2
  exit 1
fi
if [[ ! "$BIND_ADDRESS" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "[startup] Invalid bind address: ${BIND_ADDRESS}" >&2
  exit 1
fi
if [[ ! "$CONTAINER_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
  echo "[startup] Invalid container name: ${CONTAINER_NAME}" >&2
  exit 1
fi
if [[ ! "$RESTORE_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] ||
   (( RESTORE_TIMEOUT_SECONDS < 1 || RESTORE_TIMEOUT_SECONDS > 86400 )); then
  echo "[startup] Invalid VIBESTACK_RESTORE_TIMEOUT_SECONDS: ${RESTORE_TIMEOUT_SECONDS}" >&2
  exit 1
fi
if [[ ! "$PIDS_LIMIT" =~ ^[0-9]+$ ]] ||
   (( PIDS_LIMIT < 128 || PIDS_LIMIT > 4096 )); then
  echo "[startup] Invalid VIBESTACK_PIDS_LIMIT: ${PIDS_LIMIT}" >&2
  exit 1
fi

DATA_MARKER="$DATA_DIR/.vibestack-state-v1"
if [[ -e "$DATA_DIR" || -L "$DATA_DIR" ]]; then
  [[ -d "$DATA_DIR" && ! -L "$DATA_DIR" ]] || \
    data_path_error "existing path is not a directory"
  if [[ ! -d "$DATA_MARKER" || -L "$DATA_MARKER" ]]; then
    if [[ "$ADOPT_DATA" != "true" ]]; then
      data_path_error "existing directory is unmarked; review it, then pass --adopt-data once"
    fi
    [[ ! -e "$DATA_MARKER" && ! -L "$DATA_MARKER" ]] || \
      data_path_error "state marker path is occupied"
    # Adoption is intentionally limited to the state names VibeStack owns.
    # This catches a mistyped personal directory before its root is chowned.
    while IFS= read -r -d '' existing_entry; do
      existing_name="${existing_entry##*/}"
      case "$existing_name" in
        bash_history|claude.json|gitconfig)
          [[ -f "$existing_entry" && ! -L "$existing_entry" && \
             "$(stat -c '%h' -- "$existing_entry")" == "1" ]] || \
            data_path_error "VibeStack state file has an unsafe type: $existing_name" ;;
        .vibestack-auth-v1|chatgpt|chrome|claude|claude-desktop|code-server-config|code-server-data|codex|flatpak|flatpak-apps|godot-config|godot-data|keyrings|logs|lost+found|opencode|opencode-config|projects|ssh|vibestack)
          [[ -d "$existing_entry" && ! -L "$existing_entry" ]] || \
            data_path_error "VibeStack state directory has an unsafe type: $existing_name" ;;
        *)
          data_path_error "unmarked directory contains non-VibeStack entry: $existing_name" ;;
      esac
    done < <(find "$DATA_DIR" -mindepth 1 -maxdepth 1 -print0)
    mkdir -- "$DATA_MARKER"
  fi
else
  mkdir -p -- "$DATA_DIR"
  mkdir -- "$DATA_MARKER"
fi
chmod 0755 -- "$DATA_MARKER"
mkdir -p -- "$PROJECTS_DIR"

if [[ "${BUILD}" == "true" ]]; then
  echo "[startup] Building ${IMAGE_NAME}..."
  docker build -t "${IMAGE_NAME}" "${SCRIPT_DIR}"
elif ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
  echo "[startup] Image does not exist: ${IMAGE_NAME}" >&2
  exit 1
fi

echo "[startup] Starting ${CONTAINER_NAME} on ${BIND_ADDRESS}:${PORT}"
echo "[startup]   state:    ${DATA_DIR} -> /data"
echo "[startup]   projects: ${PROJECTS_DIR} -> /projects"
run_args=(-d --name "${CONTAINER_NAME}" --restart unless-stopped --hostname vibestack \
  --label dev.vibestack.launch-contract=1 \
  --label dev.vibestack.runner.managed=false)
if [[ "$MOUNT_SOURCE" == true ]]; then
  echo "[startup]   source:   ${SCRIPT_DIR} -> /projects/${SOURCE_NAME} (read/write)"
  run_args+=(--mount "type=bind,source=${SCRIPT_DIR},target=/projects/${SOURCE_NAME}")
  run_args+=(-e "VIBESTACK_SOURCE_PROJECT=${SOURCE_NAME}")
fi
[[ -n "$ALLOWED_HOSTS" ]] && run_args+=(-e "VIBESTACK_ALLOWED_HOSTS=$ALLOWED_HOSTS")
[[ "${SKIP_SETUP}" == "true" ]] && run_args+=(-e VIBESTACK_SKIP_SETUP=1)
if [[ "${FLATPAK_MODE}" == "true" ]]; then
  echo "[startup] Flatpak mode: nested app sandboxes enabled for this trusted container"
  echo "[startup]   security: Docker seccomp, AppArmor, and protected system paths relaxed"
  run_args+=(
    -e VIBESTACK_FLATPAK_ENABLED=1
    --security-opt seccomp=unconfined
    --security-opt apparmor=unconfined
    --security-opt systempaths=unconfined
  )
fi

PREVIOUS_CONTAINER=""
restore_previous() {
  local failed_status="${1:-1}"
  trap - INT TERM
  if [[ -n "$PREVIOUS_CONTAINER" ]] && \
     docker ps -a --format '{{.Names}}' | grep -Fxq "$PREVIOUS_CONTAINER"; then
    if docker ps -a --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
      docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    fi
    echo "[startup] Restoring previous container after candidate failure..." >&2
    docker rename "$PREVIOUS_CONTAINER" "${CONTAINER_NAME}" >/dev/null
    docker start "${CONTAINER_NAME}" >/dev/null
  elif [[ -n "$PREVIOUS_CONTAINER" ]] && \
       docker ps -a --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
    # The original may have stopped before it could be renamed.
    docker start "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  elif [[ -z "$PREVIOUS_CONTAINER" ]] && \
       docker ps -a --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi
  exit "$failed_status"
}

if docker ps -a --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
  PREVIOUS_CONTAINER="${CONTAINER_NAME}-rollback-$(date +%s)-$$"
  echo "[startup] Holding existing container as ${PREVIOUS_CONTAINER}..."
  trap 'restore_previous 130' INT TERM
  if ! docker stop --timeout 20 "${CONTAINER_NAME}" >/dev/null; then
    docker start "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    trap - INT TERM
    exit 1
  fi
  if ! docker rename "${CONTAINER_NAME}" "$PREVIOUS_CONTAINER"; then
    docker start "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    trap - INT TERM
    exit 1
  fi
fi
trap 'restore_previous 130' INT TERM

publish_args=(-p "${BIND_ADDRESS}:${PORT}:80")
(( SSH_PORT == 0 )) || publish_args+=(-p "${BIND_ADDRESS}:${SSH_PORT}:22")
(( NATIVE_VNC_HOST_PORT == 0 )) || publish_args+=(-p "${BIND_ADDRESS}:${NATIVE_VNC_HOST_PORT}:5901")

if ! docker run "${run_args[@]}" \
    --shm-size=1g \
    --pids-limit="$PIDS_LIMIT" \
    "${publish_args[@]}" \
    -e "VIBESTACK_INSTANCE_NAME=${CONTAINER_NAME}" \
    -e "VIBESTACK_PUBLIC_PORT=${PORT}" \
    -e "VIBESTACK_SSH_PORT=${SSH_PORT}" \
    -e "VIBESTACK_NATIVE_VNC_PORT=${NATIVE_VNC_HOST_PORT}" \
    -e "VIBESTACK_PUBLIC_URL=${VIBESTACK_PUBLIC_URL:-http://${BIND_ADDRESS}:${PORT}}" \
    -v "${DATA_DIR}:/data" \
    -v "${PROJECTS_DIR}:/projects" \
    "${IMAGE_NAME}" >/dev/null; then
  restore_previous 1
fi

echo "[startup] Waiting for container health..."
candidate_healthy=false
for _ in $(seq 1 60); do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
  if [[ "$health" == "healthy" ]]; then
    candidate_healthy=true
    break
  fi
  if [[ "$health" == "unhealthy" || -z "$health" ]]; then
    docker logs --tail 200 "${CONTAINER_NAME}" >&2 || true
    restore_previous 1
  fi
  sleep 2
done
if [[ "$candidate_healthy" != "true" ]]; then
  echo "[startup] Candidate did not become healthy." >&2
  docker logs --tail 200 "${CONTAINER_NAME}" >&2 || true
  restore_previous 1
fi

# Optional applications live in the container layer while their intended set
# lives under /data. Keep a stopped rollback container until the setup service
# confirms that every saved, auto-restored component is present in the new
# layer. A base-service health result alone is not enough to discard it.
component_restore_status() {
  docker exec -u vibe -w / "${CONTAINER_NAME}" \
    /usr/bin/env -i HOME=/home/vibe USER=vibe LOGNAME=vibe \
    PATH=/usr/bin:/bin LANG=C LC_ALL=C \
    /usr/bin/python3 -I -c '
import json
from urllib.request import urlopen

# This is an operator-local probe, not an unauthenticated browser API. Its
# fixed loopback backend remains private to the desktop account.
with urlopen("http://127.0.0.1:7999/api/state", timeout=10) as response:
    payload = json.load(response)

def fail(reason):
    print("failed:" + reason)
    raise SystemExit(0)

if not isinstance(payload, dict):
    fail("state-response-invalid")
if payload.get("state_valid") is not True:
    error = payload.get("state_error")
    code = error.get("code") if isinstance(error, dict) else None
    if code not in {"state_invalid", "state_unreadable", "state_version_unsupported"}:
        fail("state-response-invalid")
    fail("state-" + code)

state = payload.get("state")
job = payload.get("job")
missing = payload.get("missing")
unknown = payload.get("unknown_selected")
unsupported = payload.get("unsupported_selected")
if (
    payload.get("state_error") is not None
    or not isinstance(state, dict)
    or not isinstance(job, dict)
    or not isinstance(missing, list)
    or not isinstance(unknown, list)
    or not isinstance(unsupported, list)
    or not all(
        isinstance(item, str) and item
        for item in missing + unknown + unsupported
    )
    or not set(unknown).issubset(missing)
    or not set(unsupported).issubset(missing)
    or not isinstance(state.get("completed"), bool)
    or not isinstance(state.get("auto_restore"), bool)
    or not isinstance(job.get("running"), bool)
):
    fail("state-response-invalid")
if not state["completed"] or not state["auto_restore"]:
    print("not-required")
elif job["running"]:
    print("waiting")
elif unsupported:
    print("failed:unsupported-" + ",".join(unsupported))
elif missing:
    print("failed:" + ",".join(missing))
else:
    print("ready")
'
}

echo "[startup] Checking saved component restoration..."
restore_deadline=$((SECONDS + RESTORE_TIMEOUT_SECONDS))
restore_notice_at=$SECONDS
while true; do
  if ! restore_status="$(component_restore_status 2>/dev/null)"; then
    restore_status="failed:state-response-invalid"
  fi
  case "$restore_status" in
    ready)
      echo "[startup] Saved components are ready."
      break ;;
    not-required)
      echo "[startup] No saved component restoration is required."
      break ;;
    failed:*)
      echo "[startup] Saved component restoration failed (${restore_status#failed:})." >&2
      docker logs --tail 200 "${CONTAINER_NAME}" >&2 || true
      restore_previous 1 ;;
  esac
  if (( SECONDS >= restore_deadline )); then
    echo "[startup] Saved component restoration did not converge within ${RESTORE_TIMEOUT_SECONDS}s." >&2
    docker logs --tail 200 "${CONTAINER_NAME}" >&2 || true
    restore_previous 1
  fi
  if (( SECONDS >= restore_notice_at )); then
    echo "[startup] Saved components are still restoring..."
    restore_notice_at=$((SECONDS + 30))
  fi
  sleep 2
done

echo "[startup] Setup:    http://${BIND_ADDRESS}:${PORT}/setup/"
echo "[startup] Terminal: http://${BIND_ADDRESS}:${PORT}/terminal/"
echo "[startup] Desktop:  http://${BIND_ADDRESS}:${PORT}/vnc/"
(( SSH_PORT == 0 )) || echo "[startup] SSH:      ssh -p ${SSH_PORT} vibe@${BIND_ADDRESS}"
(( NATIVE_VNC_HOST_PORT == 0 )) || echo "[startup] VNC:      ${BIND_ADDRESS}:${NATIVE_VNC_HOST_PORT} (Linux login)"

if [[ "${CHECK}" == "true" ]]; then
  if ! docker exec -u vibe "${CONTAINER_NAME}" vibestack-check --live --display --restart; then
    restore_previous 1
  fi
fi

trap - INT TERM
if [[ -n "$PREVIOUS_CONTAINER" ]]; then
  docker rm "$PREVIOUS_CONTAINER" >/dev/null || \
    echo "[startup] Warning: could not remove stopped rollback container ${PREVIOUS_CONTAINER}." >&2
fi

if [[ "${FOLLOW}" == "true" ]]; then
  docker logs -f "${CONTAINER_NAME}"
fi
