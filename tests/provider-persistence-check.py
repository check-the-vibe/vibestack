"""Inspect only disposable provider fixtures; never read a live account store."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import sys

SNAPSHOT = Path('/data/.vibestack-provider-acceptance.json')
STATE = Path('/data/vibestack/provider-runtime-v1.json')
DIRECTORIES = ('codex', 'opencode-config', 'opencode', 'code-server-config', 'code-server-data')


def require(condition):
    if not condition:
        raise ValueError('disposable provider persistence assertion failed')


def private_bytes(path, owner, bound):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                info.st_uid == owner and not info.st_mode & 0o077 and info.st_size <= bound)
        return os.read(fd, bound + 1)
    finally:
        os.close(fd)


def metadata_and_native_session():
    metadata = json.loads(private_bytes(STATE, 1000, 1 << 20))
    require(sorted(metadata['selected']) == ['codex', 'opencode'])
    conversations = list(metadata['conversations'].values())
    require(len(conversations) == 1)
    conversation = conversations[0]
    require(conversation['provider'] == 'opencode' and conversation['status'] == 'idle'
            and not conversation['operations'] and conversation['native'])
    # Pinned OpenCode 1.18.29 schema, measured in the actual native fixture.
    # Read-only access proves the native session survives, not just our mapping.
    with sqlite3.connect('file:/data/opencode/opencode.db?mode=ro', uri=True) as db:
        row = db.execute('select id, directory, permission, model from session where id = ?',
                         (conversation['native'],)).fetchone()
        require(row is not None and row[1] == '/projects/' + conversation['project'])
    return {'metadata': metadata, 'native_session': list(row)}


def main():
    require(os.geteuid() == 0 and os.environ.get('VIBESTACK_DISPOSABLE_PROVIDER_MIGRATION') == '1')
    require(len(sys.argv) == 2 and sys.argv[1] in ('prepare', 'verify'))
    current = metadata_and_native_session()
    sentinels = {}
    for name in DIRECTORIES:
        directory = Path('/data') / name
        require(directory.is_dir() and not directory.is_symlink())
        path = directory / '.vibestack-acceptance-preservation'
        if sys.argv[1] == 'prepare':
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                os.fchown(fd, 1000, 1000)
                os.write(fd, secrets.token_bytes(48))
            finally:
                os.close(fd)
        sentinels[name] = hashlib.sha256(private_bytes(path, 1000, 48)).hexdigest()
    current['sentinels'] = sentinels
    if sys.argv[1] == 'prepare':
        fd = os.open(SNAPSHOT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(current, stream)
    else:
        require(json.loads(private_bytes(SNAPSHOT, 0, 1 << 20)) == current)
    print('PASS disposable provider metadata, native OpenCode session and protected data sentinels preserved; no account or model call')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('FAIL disposable provider persistence (private payload suppressed)', file=sys.stderr)
        sys.exit(1)
