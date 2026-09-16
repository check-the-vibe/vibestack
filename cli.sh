#!/bin/sh
# Install the versioned VibeStack client without sudo or profile edits.
set -eu

version="0.2.0"
install_dir="${VIBESTACK_INSTALL_DIR:-${HOME}/.local/bin}"
release_base="${VIBESTACK_RELEASE_BASE:-https://github.com/check-the-vibe/vibestack/releases/download}"
server=""

usage() {
  printf '%s\n' 'usage: cli.sh [--version VERSION] [--install-dir DIRECTORY] [--server URL]'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; version="$2"; shift 2 ;;
    --version=*) version=${1#*=}; shift ;;
    --install-dir) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; install_dir="$2"; shift 2 ;;
    --install-dir=*) install_dir=${1#*=}; shift ;;
    --server) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; server="$2"; shift 2 ;;
    --server=*) server=${1#*=}; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

case "$version" in
  v*) release_version=$version; binary_version=${version#v} ;;
  *) release_version="v$version"; binary_version=$version ;;
esac
case "$binary_version" in
  ''|*[!0-9A-Za-z._-]*) printf '%s\n' 'cli.sh: invalid version' >&2; exit 2 ;;
esac

case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=darwin ;;
  *) printf '%s\n' 'cli.sh: only Linux and macOS are supported' >&2; exit 1 ;;
esac
case "$(uname -m)" in
  x86_64|amd64) arch=amd64 ;;
  arm64|aarch64) arch=arm64 ;;
  *) printf '%s\n' 'cli.sh: only amd64 and arm64 are supported' >&2; exit 1 ;;
esac

asset="vibestack_${binary_version}_${os}_${arch}"
url="${release_base%/}/${release_version}/${asset}"
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/vibestack-cli.XXXXXXXX")
staged=
cleanup() {
  [ -z "$staged" ] || rm -f -- "$staged"
  rm -rf "$tmp_dir"
}
trap cleanup EXIT HUP INT TERM

curl -fL --proto '=https' --tlsv1.2 --max-time 300 -o "$tmp_dir/vibestack" "$url"
curl -fL --proto '=https' --tlsv1.2 --max-time 60 -o "$tmp_dir/checksum" "$url.sha256"
expected=$(awk 'NR == 1 && $1 ~ /^[0-9a-fA-F]{64}$/ { print tolower($1) }' "$tmp_dir/checksum")
[ -n "$expected" ] || { printf '%s\n' 'cli.sh: release checksum is invalid' >&2; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then
  actual=$(sha256sum "$tmp_dir/vibestack" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
  actual=$(shasum -a 256 "$tmp_dir/vibestack" | awk '{print $1}')
else
  printf '%s\n' 'cli.sh: a SHA-256 utility is required' >&2
  exit 1
fi
[ "$actual" = "$expected" ] || { printf '%s\n' 'cli.sh: checksum verification failed; the existing installation was preserved' >&2; exit 1; }

mkdir -p "$install_dir"
[ -d "$install_dir" ] && [ ! -L "$install_dir" ] || { printf '%s\n' 'cli.sh: install directory must be a real directory' >&2; exit 1; }
chmod 0755 "$tmp_dir/vibestack"
staged=$(mktemp "$install_dir/.vibestack.${binary_version}.XXXXXXXX")
cp "$tmp_dir/vibestack" "$staged"
chmod 0755 "$staged"
mv -f "$staged" "$install_dir/vibestack"
staged=

printf 'Installed VibeStack CLI %s at %s/vibestack\n' "$binary_version" "$install_dir"
case ":${PATH}:" in
  *":${install_dir}:"*) ;;
  *) printf 'Add %s to PATH in your shell profile, then open a new terminal.\n' "$install_dir" ;;
esac
if [ -n "$server" ]; then
  printf "Next: vibestack connect --name my-workspace --url '%s'\n" "$server"
fi
printf '%s\n' 'HTTPS authenticates the download source; the published SHA-256 detects corruption or substitution within that release channel.'
