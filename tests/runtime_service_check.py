"""Boundary checks run as root only in the disposable acceptance container."""
import http.client
import json
import os
from pathlib import Path
import shutil

PUBLISH = Path('/usr/share/vibestack/public')
FIXTURE = PUBLISH / 'acceptance-publish-boundary'
PRIVATE = Path('/tmp/vibestack-private-publish-sentinel')


def request(path, method='GET', headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', 80, timeout=10)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read(65536)
    finally:
        connection.close()


def main():
    # No production target: the fixture name and owner credential are created
    # by bin/vibestack-dev accept, never by the live-check workflow.
    token = Path('/data/vibestack/acceptance-owner.token').read_text().strip()
    if FIXTURE.exists() or PRIVATE.exists():
        raise RuntimeError('Disposable publish fixture already exists')
    FIXTURE.mkdir(mode=0o755)
    PRIVATE.write_text('private-publish-sentinel')
    PRIVATE.chmod(0o644)
    try:
        for name in ['visible.txt', '.env', 'credentials.json', 'private.key']:
            (FIXTURE / name).write_text('publish-fixture')
            (FIXTURE / name).chmod(0o644)
        (FIXTURE / 'escape.txt').symlink_to(PRIVATE)
        (FIXTURE / 'inside.txt').symlink_to(FIXTURE / 'visible.txt')
        os.link(FIXTURE / 'visible.txt', FIXTURE / 'hardlink.txt')
        # Both links must be denied while the file has multiple hard links.
        denied = ['/.git/config', '/Dockerfile', '/data/vibestack/identity',
                  '/acceptance-publish-boundary/', '/acceptance-publish-boundary/.env',
                  '/acceptance-publish-boundary/credentials.json',
                  '/acceptance-publish-boundary/private.key',
                  '/acceptance-publish-boundary/escape.txt',
                  '/acceptance-publish-boundary/inside.txt',
                  '/acceptance-publish-boundary/hardlink.txt',
                  '/acceptance-publish-boundary/visible.txt',
                  '/acceptance-publish-boundary/%2e%2e/%2e%2e/etc/passwd']
        for path in denied:
            status, body = request(path)
            if status not in (400, 403, 404) or b'private-publish-sentinel' in body or b'publish-fixture' in body:
                raise RuntimeError('Static publication boundary failed for ' + path)
        (FIXTURE / 'hardlink.txt').unlink()
        status, body = request('/acceptance-publish-boundary/visible.txt')
        assert status == 200 and body == b'publish-fixture', 'Explicit publication failed'
        assert request('/acceptance-publish-boundary/visible.txt', 'POST')[0] == 405
        for path in ['/api/v1/status', '/api/v1/files', '/setup/api/status', '/mcp']:
            assert request(path)[0] == 401, 'Missing credential was accepted: ' + path
            assert request(path, headers={'Authorization':'Bearer invalid'})[0] == 401
        assert request('/api/v1/status', headers={'Authorization':'Bearer ' + token})[0] == 200
        assert request('/api/v1/status', headers={'X-Forwarded-User':'owner'})[0] == 401
        assert request('/api/v1/status', headers={'Authorization':'Bearer ' + token,
                       'Origin':'https://attacker.invalid'})[0] == 403
        discovery = json.loads(request('/.well-known/vibestack')[1])
        assert 'identity' in discovery
        print('PASS service publication, nginx authentication, forged identity and Origin boundaries')
    finally:
        shutil.rmtree(FIXTURE)
        PRIVATE.unlink()


if __name__ == '__main__':
    main()
