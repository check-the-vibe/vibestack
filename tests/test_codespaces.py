"""Lifecycle behavior without touching the developer's Docker daemon."""
import copy
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("codespaces", ROOT / ".devcontainer/codespaces.py")
codespaces = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codespaces)


class CodespacesTests(unittest.TestCase):
    def setUp(self):
        self.data = Path('/vibestack-runtime/vibestack/data')
        self.projects = self.data.parent / 'projects'
        self.host = 'test-desktop-8080.app.github.dev'
        self.container = {
            'Image': 'sha256:test',
            'Config': {'Labels': {'dev.vibestack.launch-contract': '1'},
                       'Env': [f'VIBESTACK_ALLOWED_HOSTS={self.host}']},
            'Mounts': [{'Type': 'bind', 'Source': str(self.data), 'Destination': '/data'},
                       {'Type': 'bind', 'Source': str(self.projects), 'Destination': '/projects'},
                       {'Type': 'bind', 'Source': str(ROOT), 'Destination': f'/projects/{ROOT.name}', 'RW': True}],
            'State': {'Running': True, 'Health': {'Status': 'healthy'}},
        }

    def exercise(self, existing):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(codespaces, 'inspect', side_effect=[{'Id': 'sha256:test'}, existing, self.container]), \
             patch.object(codespaces, 'run') as run, \
             patch.object(codespaces.urllib.request, 'urlopen', return_value=response) as urlopen:
            codespaces.start(self.data, self.projects, self.host)
            self.assertEqual(urlopen.call_args.args[0].get_header('Host'), self.host)
            self.assertEqual(urlopen.call_args.args[0].full_url, 'http://127.0.0.1:8080/healthz')
            return run.call_args_list

    def test_resume_keeps_existing_container_and_its_layer(self):
        stopped = copy.deepcopy(self.container)
        stopped['State']['Running'] = False
        calls = self.exercise(stopped)
        self.assertEqual([c.args for c in calls], [('docker', 'start', codespaces.CONTAINER)])
        self.assertEqual(self.exercise(self.container), [])

    def test_fresh_start_uses_separate_state_and_exact_private_origin(self):
        calls = self.exercise(None)
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args[0], 'bash')
        for flag, value in [('--bind', '127.0.0.1'), ('--ssh-port', '0'),
                            ('--vnc-port', '0'), ('--allowed-host', self.host),
                            ('--data', str(self.data)), ('--projects', str(self.projects))]:
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertEqual(kwargs['env']['VIBESTACK_PUBLIC_URL'], 'https://' + self.host)
        self.assertNotIn('--skip-setup', args)
        self.assertIn('--mount-source', args)

    def test_old_codespace_without_source_mount_is_replaced(self):
        old = copy.deepcopy(self.container)
        old['Mounts'].pop()
        self.assertEqual(self.exercise(old)[0].args[0], 'bash')

    def test_unexpected_source_mount_is_not_adopted(self):
        for key, value in [('Source', '/another/repository'), ('RW', False)]:
            wrong = copy.deepcopy(self.container)
            wrong['Mounts'][-1][key] = value
            with self.assertRaisesRegex(RuntimeError, 'source mount'):
                self.exercise(wrong)

    def test_changed_image_or_hostname_replaces_through_normal_launcher(self):
        for key, value in [('Image', 'sha256:old'), ('Config', {'Labels': {'dev.vibestack.launch-contract': '1'}, 'Env': []})]:
            old = copy.deepcopy(self.container)
            old[key] = value
            self.assertEqual(self.exercise(old)[0].args[0], 'bash')

    def test_unexpected_mounts_fail_without_mutation(self):
        wrong = copy.deepcopy(self.container)
        wrong['Mounts'][0]['Source'] = '/personal/data'
        with patch.object(codespaces, 'inspect', side_effect=[{'Id': 'sha256:test'}, wrong]), \
             patch.object(codespaces, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'unexpected mounts'):
                codespaces.start(self.data, self.projects, self.host)
            run.assert_not_called()

    def test_outside_codespaces_is_a_noop(self):
        with patch.dict(os.environ, {}, clear=True), patch('sys.argv', ['codespaces.py', 'start']), \
             patch.object(codespaces, 'run') as run:
            codespaces.main()
            run.assert_not_called()

    def test_prebuild_prepares_only_image_without_creating_runtime_identity(self):
        with patch.dict(os.environ, {'CODESPACES': 'true'}), \
             patch('sys.argv', ['codespaces.py', 'prepare']), \
             patch.object(codespaces, 'ROOT', Path('/workspaces/vibestack')), \
             patch.object(codespaces, 'runtime_state') as state, \
             patch.object(codespaces, 'wait_for_docker'), \
             patch.object(codespaces, 'run') as run:
            codespaces.main()
            state.assert_not_called()
            run.assert_called_once_with('docker', 'build', '-t', codespaces.IMAGE, '/workspaces/vibestack')

    def test_host_requires_complete_valid_environment(self):
        with patch.dict(os.environ, {'CODESPACE_NAME': 'test-desktop', 'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN': 'app.github.dev'}):
            self.assertEqual(codespaces.public_host(), self.host)
        for domain in ['', '*.app.github.dev', 'app.github.dev/anything']:
            with patch.dict(os.environ, {'CODESPACE_NAME': 'test-desktop', 'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN': domain}):
                with self.assertRaises((RuntimeError, ValueError)):
                    codespaces.public_host()

    def test_missing_runtime_mount_fails_before_creating_state(self):
        with tempfile.TemporaryDirectory() as name:
            runtime = Path(name) / 'runtime'
            with patch.object(codespaces, 'RUNTIME', runtime):
                with self.assertRaisesRegex(RuntimeError, 'volume is missing'):
                    codespaces.runtime_state()
            self.assertFalse(runtime.exists())

    def test_runtime_identity_detects_volume_loss_without_resetting_state(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            runtime = base / 'volume'
            runtime.mkdir()
            root = base / 'workspaces' / 'vibestack'
            root.mkdir(parents=True)
            with patch.object(codespaces, 'RUNTIME', runtime), patch.object(codespaces, 'ROOT', root), patch.object(Path, 'is_mount', return_value=True):
                state = codespaces.runtime_state()
                self.assertEqual(codespaces.runtime_state(), state)
                identity = state / '.volume-id'
                expected = identity.read_text()
                identity.unlink()
                with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                    codespaces.runtime_state()
                self.assertFalse(identity.exists())
                identity.write_text('f' * 32)
                with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                    codespaces.runtime_state()
                identity.write_text(expected)
                self.assertEqual(codespaces.runtime_state(), state)

    def test_legacy_state_requires_migration_and_is_preserved(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            runtime = base / 'volume'
            runtime.mkdir()
            root = base / 'workspaces' / 'vibestack'
            root.mkdir(parents=True)
            old = root.parent / '.vibestack-codespaces' / root.name / 'data'
            old.mkdir(parents=True)
            sentinel = old / 'keep'
            sentinel.write_text('original')
            with patch.object(codespaces, 'RUNTIME', runtime), patch.object(codespaces, 'ROOT', root), patch.object(Path, 'is_mount', return_value=True):
                with self.assertRaisesRegex(RuntimeError, 'explicit migration'):
                    codespaces.runtime_state()
            self.assertEqual(sentinel.read_text(), 'original')
            self.assertEqual(list(runtime.iterdir()), [])

    def test_metadata_rejects_links_devices_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / 'id'
            source.write_text('a' * 32)
            link = base / 'link'
            link.symlink_to(source)
            with self.assertRaises(OSError):
                codespaces.read_metadata(link)
            fifo = base / 'fifo'
            os.mkfifo(fifo)
            with self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                codespaces.read_metadata(fifo)
            source.write_text('a' * 4097)
            with self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                codespaces.read_metadata(source)
            source.write_text('a' * 32)
            os.link(source, base / 'hardlink')
            with self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                codespaces.read_metadata(source)

    def test_migration_marker_only_allows_checked_old_container(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / 'workspaces' / 'vibestack'
            data = Path(name) / 'volume' / 'data'
            data.parent.mkdir()
            legacy = root.parent / '.vibestack-codespaces' / root.name
            old = copy.deepcopy(self.container)
            old['Mounts'][0]['Source'] = str(legacy / 'data')
            old['Mounts'][1]['Source'] = str(legacy / 'projects')
            old['Mounts'][2]['Source'] = str(root)
            old['Mounts'][2]['Destination'] = '/projects/vibestack'
            marker = data.parent / '.migrated-from-workspaces'
            with patch.object(codespaces, 'ROOT', root):
                self.assertFalse(codespaces.migrated_existing(old, data, data.parent / 'projects', self.host))
                marker.write_text(str(legacy))
                self.assertTrue(codespaces.migrated_existing(old, data, data.parent / 'projects', self.host))
                old['Mounts'][1]['Source'] = '/unrelated'
                with self.assertRaisesRegex(RuntimeError, 'unexpected mounts'):
                    codespaces.migrated_existing(old, data, data.parent / 'projects', self.host)

    def test_migration_preserves_original_and_refuses_a_second_copy(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            root = base / 'workspaces' / 'vibestack'
            legacy = root.parent / '.vibestack-codespaces' / root.name
            (legacy / 'data' / '.vibestack-state-v1').mkdir(parents=True)
            (legacy / 'projects').mkdir()
            original = legacy / 'projects' / 'keep.txt'
            original.write_text('preserved')
            runtime = base / 'volume'
            runtime.mkdir()
            def copy(*args):
                self.assertEqual(args[:6], ('sudo', '-n', '--', 'cp', '-a', '--'))
                for source in args[6:8]:
                    shutil.copytree(source, Path(args[8]) / Path(source).name)
            with patch.object(codespaces, 'ROOT', root), patch.object(codespaces, 'RUNTIME', runtime), \
                 patch.object(Path, 'is_mount', return_value=True), \
                 patch.object(codespaces, 'inspect', return_value=None), patch.object(codespaces, 'run', side_effect=copy):
                codespaces.migrate()
                state = codespaces.runtime_state()
                self.assertEqual((state / 'projects' / 'keep.txt').read_text(), 'preserved')
                self.assertEqual(original.read_text(), 'preserved')
                with self.assertRaisesRegex(RuntimeError, 'already exists'):
                    codespaces.migrate()
