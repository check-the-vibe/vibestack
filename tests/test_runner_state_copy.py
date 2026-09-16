import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('state_copy', Path(__file__).resolve().parents[1] / 'runner/state_copy.py')
copy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(copy)

class StateCopyTests(unittest.TestCase):
    def test_independent_copy_preserves_password_and_app_state_but_not_machine_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, one, two = (root / name for name in ('source', 'one', 'two'))
            for p in (source, one, two): p.mkdir()
            kept = ['.vibestack-auth-v1/vibe.shadow', 'keyrings/login.keyring', 'chrome/Default/Cookies', 'codex/auth.json', 'vibestack/setup-state.json']
            excluded = ['.vibestack-auth-v1/ssh_host_ed25519_key', 'vibestack/automation.token', 'vibestack/identity', 'vibestack/pairing.key', 'vibestack/client-credentials.json', 'vibestack/automation/jobs/old.json', 'logs/vibestack/access.log', 'chrome/SingletonLock', 'vibestack/install.lock', 'ssh/authorized_keys', 'ssh/vibestack_authorized_keys']
            for name in kept + excluded:
                p = source / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('sentinel'); p.chmod(0o600)
            os.symlink('/unavailable/external', source / 'app-link')
            os.mkfifo(source / 'runtime-pipe')
            copy.copy_dir(source, one); copy.copy_dir(source, two)
            for name in kept:
                self.assertEqual((one / name).read_text(), 'sentinel')
                self.assertEqual((one / name).stat().st_mode & 0o777, 0o600)
            for name in excluded: self.assertFalse((one / name).exists(), name)
            self.assertFalse((one / 'runtime-pipe').exists())
            self.assertTrue((one / 'app-link').is_symlink())
            (one / 'codex/auth.json').write_text('changed')
            self.assertEqual((two / 'codex/auth.json').read_text(), 'sentinel')
            self.assertEqual((source / 'codex/auth.json').read_text(), 'sentinel')
