"""Lifecycle behavior without touching the developer's Docker daemon."""
import copy
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("codespaces", ROOT / ".devcontainer/codespaces.py")
codespaces = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codespaces)


class CodespacesTests(unittest.TestCase):
    def setUp(self):
        self.data = Path('/workspaces/.vibestack-codespaces/vibestack/data')
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

    def test_host_requires_complete_valid_environment(self):
        with patch.dict(os.environ, {'CODESPACE_NAME': 'test-desktop', 'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN': 'app.github.dev'}):
            self.assertEqual(codespaces.public_host(), self.host)
        for domain in ['', '*.app.github.dev', 'app.github.dev/anything']:
            with patch.dict(os.environ, {'CODESPACE_NAME': 'test-desktop', 'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN': domain}):
                with self.assertRaises((RuntimeError, ValueError)):
                    codespaces.public_host()
