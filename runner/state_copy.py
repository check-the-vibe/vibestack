# Executed only in an approved image with fixed /source (read-only) and /target mounts.
import os
import shutil
import stat

EXCLUDED = {
    'logs', 'projects', 'bash_history',
    'vibestack/automation.token', 'vibestack/automation', 'vibestack/identity', 'vibestack/pairing.key',
    'vibestack/pairing-requests.json', 'vibestack/client-credentials.json',
    'vibestack/jobs', 'vibestack/operations',
    'ssh/authorized_keys', 'ssh/vibestack_authorized_keys',
}

def excluded(rel, name):
    return (rel in EXCLUDED or
            rel.startswith('.vibestack-auth-v1/ssh_host_') or
            name in ('SingletonLock', 'SingletonCookie', 'SingletonSocket', 'LOCK', 'lock') or
            name.endswith(('.lock', '.sock', '.pid')) or
            name.startswith(('.ssh-key-', '.ssh-public-', '.tmp-')))

def copy_dir(source, target, rel=''):
    for entry in os.scandir(source):
        child = rel + '/' + entry.name if rel else entry.name
        if excluded(child, entry.name):
            continue
        info = entry.stat(follow_symlinks=False)
        dest = os.path.join(target, entry.name)
        if stat.S_ISLNK(info.st_mode):
            os.symlink(os.readlink(entry.path), dest)
        elif stat.S_ISDIR(info.st_mode):
            os.mkdir(dest, 0o700)
            copy_dir(entry.path, dest, child)
            shutil.copystat(entry.path, dest, follow_symlinks=False)
        elif stat.S_ISREG(info.st_mode):
            shutil.copy2(entry.path, dest, follow_symlinks=False)
        else:
            continue  # sockets, FIFOs and devices are runtime state, never seeds
        os.chown(dest, info.st_uid, info.st_gid, follow_symlinks=False)

if __name__ == '__main__':
    # A failed or interrupted copy is never a seed. Retry requires a new target.
    if os.listdir('/target'):
        raise RuntimeError('state copy target is not empty')
    copy_dir('/source', '/target')
    os.sync()
