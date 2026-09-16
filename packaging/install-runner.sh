#!/bin/sh
# Operator-only host installation for Ubuntu 24.04/26.04.
set -eu

install_docker=0
case "${1:-}" in
  --install-docker) install_docker=1; shift ;;
  '') ;;
  *) printf '%s\n' 'usage: install-runner.sh [--install-docker]' >&2; exit 2 ;;
esac
[ "$#" -eq 0 ] || { printf '%s\n' 'usage: install-runner.sh [--install-docker]' >&2; exit 2; }

[ "$(id -u)" -eq 0 ] || { printf '%s\n' 'install-runner.sh must be run as root' >&2; exit 1; }
[ -r /etc/os-release ] || { printf '%s\n' 'This systemd package supports Ubuntu 24.04 and 26.04 only.' >&2; exit 1; }
. /etc/os-release
[ "${ID:-}" = ubuntu ] && { [ "${VERSION_ID:-}" = 24.04 ] || [ "${VERSION_ID:-}" = 26.04 ]; } || {
  printf '%s\n' 'This package supports Ubuntu 24.04 and 26.04. Run the runner in the foreground on other Docker hosts.' >&2
  exit 1
}
command -v systemctl >/dev/null 2>&1 || { printf '%s\n' 'systemd is required by this package' >&2; exit 1; }
case "$(uname -m)" in
  x86_64|amd64|aarch64|arm64) ;;
  *) printf '%s\n' 'The runner release supports amd64 and arm64 only' >&2; exit 1 ;;
esac
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -x "$script_dir/vibestack-runner" ] || { printf '%s\n' 'place the release vibestack-runner binary beside this script' >&2; exit 1; }

install_docker_engine() {
  conflicts=
  for package in docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc; do
    status=$(dpkg-query -W -f='${db:Status-Abbrev}' "$package" 2>/dev/null || true)
    case "$status" in ii*) conflicts="$conflicts $package" ;; esac
  done
  if [ -n "$conflicts" ]; then
    printf 'Conflicting packages are installed:%s\n' "$conflicts" >&2
    printf '%s\n' 'They were not removed. Review Docker official installation guidance and resolve them explicitly.' >&2
    exit 1
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl
  install -d -m 0755 /etc/apt/keyrings
  key_tmp=$(mktemp /tmp/vibestack-docker-key.XXXXXXXX)
  trap 'rm -f "$key_tmp"' EXIT HUP INT TERM
  curl -fsSL --proto '=https' --tlsv1.2 https://download.docker.com/linux/ubuntu/gpg -o "$key_tmp"
  install -m 0644 "$key_tmp" /etc/apt/keyrings/docker.asc
  rm -f "$key_tmp"
  trap - EXIT HUP INT TERM
  if [ ! -e /etc/apt/sources.list.d/docker.sources ]; then
    docker_arch=$(dpkg --print-architecture)
    docker_suite=${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}
    [ -n "$docker_suite" ] || { printf '%s\n' 'Ubuntu suite could not be determined' >&2; exit 1; }
    printf '%s\n' \
      'Types: deb' \
      'URIs: https://download.docker.com/linux/ubuntu' \
      "Suites: $docker_suite" \
      'Components: stable' \
      "Architectures: $docker_arch" \
      'Signed-By: /etc/apt/keyrings/docker.asc' \
      > /etc/apt/sources.list.d/docker.sources
    chmod 0644 /etc/apt/sources.list.d/docker.sources
  else
    printf '%s\n' 'Preserving existing /etc/apt/sources.list.d/docker.sources.'
  fi
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

if ! command -v docker >/dev/null 2>&1; then
  if [ "$install_docker" -eq 1 ]; then
    install_docker_engine
  else
    printf '%s\n' 'Docker is not installed. Rerun with --install-docker for the explicit official-repository step.' >&2
    printf '%s\n' 'Existing conflicting packages are never removed automatically.' >&2
    printf '%s\n' 'Reference: https://docs.docker.com/engine/install/ubuntu/' >&2
    exit 1
  fi
fi
docker version >/dev/null 2>&1 || { printf '%s\n' 'Docker is installed but the daemon is unavailable' >&2; exit 1; }

install -d -o root -g root -m 0700 /var/lib/vibestack-runner
install -d -o root -g root -m 0755 /etc/vibestack-runner
install -o root -g root -m 0755 "$script_dir/vibestack-runner" /usr/local/sbin/vibestack-runner
install -o root -g root -m 0644 "$script_dir/vibestack-runner.service" /etc/systemd/system/vibestack-runner.service
if [ ! -e /etc/vibestack-runner/config.json ]; then
  /usr/local/sbin/vibestack-runner init --config /etc/vibestack-runner/config.json
fi
/usr/local/sbin/vibestack-runner doctor --config /etc/vibestack-runner/config.json
systemctl daemon-reload
printf '%s\n' 'Configuration is ready. Review /etc/vibestack-runner/config.json, then run:'
printf '%s\n' '  systemctl enable --now vibestack-runner'
