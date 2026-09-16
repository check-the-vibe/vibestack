#!/usr/bin/env bash
set -euo pipefail
cd /

# Establish root-owned persistent log boundaries and fresh per-boot X11 state
# before any unprivileged process starts. The helper fails closed on symlinks,
# hard links, mount crossings, special files, or raced path components.
/usr/local/bin/vibestack-bootstrap

# Custom DNS/IP names are accepted only after strict validation and explicit
# operator configuration. Nginx and the Python backends consume the same list.
/usr/bin/python3 /usr/share/vibestack-common/vibestack_hosts.py \
  /run/vibestack/nginx-hosts.map

# Publish host-selected container capabilities through a fresh root-owned
# marker. The parent runtime tree is recreated on every boot, so an
# unprivileged process cannot make setup mistake a shell environment override
# for the Docker security policy selected by startup.sh.
if [[ "${VIBESTACK_FLATPAK_ENABLED:-0}" == "1" ]]; then
  /usr/bin/install -d -o root -g root -m 0755 /run/vibestack/host
  /usr/bin/install -o root -g root -m 0444 /dev/null \
    /run/vibestack/host/flatpak-enabled
fi

# A new image starts with the desktop account locked. Reapply only the
# root-owned salted hash from persistent state; when none exists, explicitly
# keep the account locked so arbitrary sudo cannot be used before onboarding.
/usr/local/bin/vibestack-password restore >/dev/null

# SSH host identities belong to this workspace's root-private persistent
# password-state boundary. Generate them without command arguments containing
# user credentials, and never copy them between instances. Unique staging
# directories keep an interrupted first boot recoverable without exposing a
# partially generated private key at its final path.
ssh_tmp_dir=
cleanup_ssh_tmp() {
  if [[ -n "$ssh_tmp_dir" ]]; then
    /usr/bin/rm -f -- "$ssh_tmp_dir/key" "$ssh_tmp_dir/key.pub"
    /usr/bin/rmdir -- "$ssh_tmp_dir" 2>/dev/null || true
    ssh_tmp_dir=
  fi
}
trap cleanup_ssh_tmp EXIT HUP INT TERM
for ssh_kind in ed25519 rsa; do
  ssh_key="/data/.vibestack-auth-v1/ssh_host_${ssh_kind}_key"
  if [[ ! -e "$ssh_key" && ! -L "$ssh_key" ]]; then
    ssh_tmp_dir="$(/usr/bin/mktemp -d "/data/.vibestack-auth-v1/.ssh-key-${ssh_kind}.XXXXXXXX")"
    /usr/bin/ssh-keygen -q -t "$ssh_kind" -N '' -f "$ssh_tmp_dir/key"
    /usr/bin/chown root:root "$ssh_tmp_dir/key" "$ssh_tmp_dir/key.pub"
    /usr/bin/chmod 0600 "$ssh_tmp_dir/key"
    /usr/bin/chmod 0644 "$ssh_tmp_dir/key.pub"
    /usr/bin/mv "$ssh_tmp_dir/key.pub" "$ssh_key.pub"
    /usr/bin/mv "$ssh_tmp_dir/key" "$ssh_key"
    /usr/bin/rmdir "$ssh_tmp_dir"
    ssh_tmp_dir=
  fi
  [[ -f "$ssh_key" && ! -L "$ssh_key" && "$(/usr/bin/stat -c '%u:%g:%a:%h' "$ssh_key")" == '0:0:600:1' ]] || {
    echo "[entrypoint] SSH host key failed its safety check" >&2
    exit 1
  }
  if [[ ! -e "$ssh_key.pub" && ! -L "$ssh_key.pub" ]]; then
    ssh_tmp_dir="$(/usr/bin/mktemp -d "/data/.vibestack-auth-v1/.ssh-public-${ssh_kind}.XXXXXXXX")"
    /usr/bin/ssh-keygen -y -f "$ssh_key" >"$ssh_tmp_dir/key.pub"
    /usr/bin/chown root:root "$ssh_tmp_dir/key.pub"
    /usr/bin/chmod 0644 "$ssh_tmp_dir/key.pub"
    /usr/bin/mv "$ssh_tmp_dir/key.pub" "$ssh_key.pub"
    /usr/bin/rmdir "$ssh_tmp_dir"
    ssh_tmp_dir=
  fi
  [[ -f "$ssh_key.pub" && ! -L "$ssh_key.pub" && "$(/usr/bin/stat -c '%u:%g:%a:%h' "$ssh_key.pub")" == '0:0:644:1' ]] || {
    echo "[entrypoint] SSH host public key failed its safety check" >&2
    exit 1
  }
done
trap - EXIT HUP INT TERM
/usr/bin/install -d -o root -g root -m 0755 /run/sshd

# Everything beneath the user's persistent state roots is managed only after
# dropping privileges. In particular, never recursively chown /data or the
# separately mounted /projects tree.
/usr/sbin/runuser -u vibe -- /usr/local/bin/vibestack-persist

# X11 is reachable only through its per-boot MIT-MAGIC-COOKIE. Keep all
# session-discovery state under /run so stale credentials never survive a boot.
runtime_dir=/run/vibestack
xauthority_file="$runtime_dir/Xauthority"
x_cookie="$(/usr/bin/od -An -N16 -tx1 /dev/urandom | /usr/bin/tr -d ' \n')"
/usr/bin/xauth -f "$xauthority_file" add :0 MIT-MAGIC-COOKIE-1 "$x_cookie"
unset x_cookie
/usr/bin/chown root:vibe "$xauthority_file"
/usr/bin/chmod 0640 "$xauthority_file"

# The API token lives inside the already-persistent ~/.vibestack directory.
# The no-follow helper runs as vibe, and its routine output (the path only) is
# suppressed so startup never discloses credential material.
/usr/sbin/runuser -u vibe -- /usr/local/bin/vibestack-api-token ensure >/dev/null

# Unattended boots (CI, rebuilds of a known-good image) can bypass the wizard.
if [[ "${VIBESTACK_SKIP_SETUP:-}" == "1" ]]; then
  /usr/sbin/runuser -u vibe -- /usr/local/bin/vibestack-setup skip >/dev/null 2>&1 || true
fi

exec "$@"
