#!/usr/bin/env bash
set -euo pipefail
cd /

# Establish root-owned persistent log boundaries and fresh per-boot X11 state
# before any unprivileged process starts. The helper fails closed on symlinks,
# hard links, mount crossings, special files, or raced path components.
/usr/local/bin/vibestack-bootstrap

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
