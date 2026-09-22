"""Compile/add/remove an extension in a verified disposable acceptance container.

Never patches a live workspace. Invalid variants are separate short-lived
processes; the original service binary is restored even if a probe fails.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BINARY = '/usr/local/bin/vibestack-service'
SUPERVISOR = ['supervisorctl', '-c', '/etc/supervisor/supervisord.conf']
STAGE = 'configuration'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, timeout=180,
                          **kwargs).stdout


def main():
    global STAGE
    if os.environ.get('VIBESTACK_DISPOSABLE_EXTENSION_TEST') != '1':
        raise RuntimeError('explicit disposable extension test required')
    container = os.environ['VIBESTACK_EXTENSION_CONTAINER']
    if not re.fullmatch(r'vibestack-acceptance-[0-9]+', container):
        raise RuntimeError('unexpected container name')
    details = json.loads(run('docker', 'inspect', container))[0]
    image = json.loads(run('docker', 'image', 'inspect', details['Image']))[0]
    architecture = image['Architecture']
    if image['Os'] != 'linux' or architecture not in ('amd64', 'arm64'):
        raise RuntimeError('unsupported acceptance image platform')
    # Match the production Docker build, not the CI host's linker/platform.
    build_env = {**os.environ, 'CGO_ENABLED': '0', 'GOOS': 'linux',
                 'GOARCH': architecture, 'GOFLAGS': ''}
    mounts = {m['Destination']: m for m in details['Mounts']}
    data = mounts.get('/data', {})
    projects = mounts.get('/projects', {})
    if (set(mounts) != {'/data', '/projects'} or data.get('Type') != 'bind'
            or projects.get('Type') != 'bind'
            or not re.fullmatch(r'/tmp/vibestack-acceptance\.[A-Za-z0-9]{10}', data.get('Source', ''))
            or projects.get('Source') != data['Source'] + '/projects'):
        raise RuntimeError('not the isolated acceptance mounts')

    def docker(*args):
        return run('docker', 'exec', container, *args)

    def ready():
        for _ in range(60):
            result = subprocess.run(['docker', 'exec', container, 'curl', '--fail',
                                     '--silent', 'http://127.0.0.1/healthz'],
                                    capture_output=True, timeout=12)
            if result.returncode == 0:
                return
            time.sleep(1)
        raise RuntimeError('service did not become ready')

    def probe(mode):
        result = subprocess.run(['node', str(ROOT / 'tests/extension-client-check.mjs'), mode],
                                cwd=ROOT, capture_output=True, timeout=180)
        if result.returncode:
            for line in result.stderr.decode(errors='replace').splitlines():
                if re.fullmatch(r'FAIL extension clients at [A-Za-z0-9 -]+ \(private payloads suppressed\)', line):
                    print(line, file=sys.stderr)
            raise RuntimeError('extension client verification failed')

    protected = ['nginx.conf', 'service/credentials.go', 'service/server.go']
    checksums = {p: hashlib.sha256((ROOT / p).read_bytes()).digest() for p in protected}
    nginx = docker('sha256sum', '/etc/nginx/nginx.conf')
    with tempfile.TemporaryDirectory(prefix='vibestack-extension-') as temporary:
        STAGE = 'isolated source copy'
        directory = Path(temporary)
        source = directory / 'source'
        source.mkdir()
        # Copy only build inputs. No Git credentials, project data, account state,
        # browser captures, or node_modules enter the authoring sandbox.
        for name in ('api', 'contracts', 'internal', 'service', 'pkg'):
            shutil.copytree(ROOT / name, source / name)
        shutil.copytree(ROOT / 'cmd/vibestack-service', source / 'cmd/vibestack-service')
        for name in ('go.mod', 'go.sum'):
            shutil.copyfile(ROOT / name, source / name)
        original = directory / 'original'
        run('docker', 'cp', f'{container}:{BINARY}', str(original))
        registration = source / 'service/capabilities/register.go'
        initial = registration.read_text()
        anchor = 'return []Registration{{Definition: projectSummaryDefinition, Handle: projectSummary(projects)}}'
        if initial.count(anchor) != 1:
            raise RuntimeError('registration layout changed; update the authoring demonstration')
        entry = '{Definition: acceptanceEchoDefinition, Handle: acceptanceEcho}'
        definition = {
            'contract_version': 1, 'id': 'acceptance_echo',
            'description': 'Return one bounded message without reading workspace state.',
            'permission': 'workspace', 'effect': 'read', 'retry': 'safe-read',
            'timeout_ms': 1000, 'request_bytes': 4096, 'response_bytes': 8192,
            'input_schema': {'type': 'object', 'additionalProperties': False,
                             'required': ['message'], 'properties': {
                                 'message': {'type': 'string', 'maxLength': 64}}},
            'output_schema': {'type': 'object', 'additionalProperties': False,
                              'required': ['message'], 'properties': {
                                  'message': {'type': 'string', 'maxLength': 64}}},
            'rest': {'method': 'POST', 'path': '/api/v1/acceptance-echo'},
            'mcp_policy': 'enabled',
        }
        module = source / 'service/capabilities/acceptance_echo.go'
        module.write_text('''package capabilities
import ("context"; _ "embed"; "encoding/json")
//go:embed acceptance_echo.json
var acceptanceEchoDefinition []byte
func acceptanceEcho(ctx context.Context, _ Principal, raw json.RawMessage) (any, error) {
    if ctx.Err() != nil { return nil, Fail("cancelled") }
    var value struct { Message string `json:"message"` }
    if json.Unmarshal(raw, &value) != nil { return nil, Fail("invalid_input") }
    return value, nil
}
''')
        schema = module.with_suffix('.json')
        candidate = directory / 'candidate'
        for variant in ('duplicate', 'invalid-schema', 'valid'):
            STAGE = variant + ' compiled variant'
            changed = json.loads(json.dumps(definition))
            if variant == 'invalid-schema':
                del changed['input_schema']['additionalProperties']
            schema.write_text(json.dumps(changed))
            entries = ', ' + entry + (', ' + entry if variant == 'duplicate' else '')
            registration.write_text(initial.replace(anchor, anchor[:-1] + entries + '}'))
            run('go', 'build', '-buildvcs=false', '-trimpath', '-ldflags=-s -w',
                '-o', str(candidate), './cmd/vibestack-service', cwd=source,
                env=build_env)
            candidate.chmod(0o555)
            if variant == 'valid':
                break
            run('docker', 'cp', str(candidate), f'{container}:/tmp/vibestack-extension-invalid')
            failed = subprocess.run(['docker', 'exec', '-u', 'vibe', container,
                                     '/tmp/vibestack-extension-invalid', 'serve',
                                     '--listen', '127.0.0.1:0'],
                                    capture_output=True, timeout=20)
            expected = (b'duplicate or reserved capability ID: acceptance_echo'
                        if variant == 'duplicate' else b'declare unknown-field policy: acceptance_echo')
            if failed.returncode == 0 or expected not in failed.stderr or len(failed.stderr) > 4096:
                raise RuntimeError('invalid compiled registration did not reject startup')
            ready()
        print('PASS duplicate registration and invalid schema reject compiled candidate startup; original service remains healthy', flush=True)
        STAGE = 'baseline absence'
        probe('absent')
        replaced = False
        try:
            STAGE = 'temporary installation'
            docker(*SUPERVISOR, 'stop', 'vibestack-service')
            replaced = True
            run('docker', 'cp', str(candidate), f'{container}:{BINARY}')
            # docker cp over an existing image file can retain its destination
            # attributes. Normalize only this disposable executable explicitly.
            docker('chown', 'root:root', BINARY)
            docker('chmod', '0555', BINARY)
            docker(*SUPERVISOR, 'start', 'vibestack-service')
            ready()
            STAGE = 'installed extension parity'
            probe('present')
        finally:
            if replaced:
                subprocess.run(['docker', 'exec', container, *SUPERVISOR,
                                'stop', 'vibestack-service'], capture_output=True, timeout=30)
                run('docker', 'cp', str(original), f'{container}:{BINARY}')
                docker(*SUPERVISOR, 'start', 'vibestack-service')
                ready()
        STAGE = 'restored baseline absence'
        probe('absent')
        if nginx != docker('sha256sum', '/etc/nginx/nginx.conf'):
            raise RuntimeError('nginx changed during extension demonstration')
        for path, digest in checksums.items():
            if hashlib.sha256((ROOT / path).read_bytes()).digest() != digest:
                raise RuntimeError('host/authentication source changed during demonstration')
    print('PASS compiled extension add/remove through real nginx REST, MCP, CLI and Chromium; original service, identity and grants preserved; no auth/nginx edits', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Child diagnostics can contain private values. Emit only the stage/type.
        print('FAIL disposable extension authoring at ' + STAGE + ' (' + type(error).__name__ + '; child payloads suppressed)', file=sys.stderr)
        sys.exit(1)
