import base64
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import vibestack_auth as auth
from common import vibestack_hosts as hosts
from automation.sshkeys import SSHKeyError, SSHKeyStore


class WorkspacePairingTests(unittest.TestCase):
    def test_pairing_uses_separate_one_time_secret_and_revocable_credential(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            auth, "_now", return_value=1_700_000_000
        ):
            store = auth.WorkspaceClientStore(directory)
            requested = store.request_pairing("Claude on laptop", ["workspace"])
            self.assertRegex(requested["verification_code"], auth.CODE_RE)
            self.assertGreaterEqual(len(requested["polling_secret"]), 32)

            persisted = "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(directory).glob("*.json")
            )
            self.assertNotIn(requested["polling_secret"], persisted)
            self.assertEqual(
                store.poll(requested["pairing_id"], requested["polling_secret"])["status"],
                "pending",
            )
            store.approve(requested["verification_code"])
            delivered = store.poll(requested["pairing_id"], requested["polling_secret"])
            self.assertTrue(store.authenticate(delivered["credential"]))

            persisted = "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(directory).glob("*.json")
            )
            self.assertNotIn(requested["polling_secret"], persisted)
            self.assertNotIn(delivered["credential"], persisted)
            with self.assertRaises(auth.ClientAuthError):
                store.poll(requested["pairing_id"], requested["polling_secret"])

            store.revoke(delivered["client_id"])
            self.assertFalse(store.authenticate(delivered["credential"]))
            for path in Path(directory).iterdir():
                if path.is_file():
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)

    def test_pairing_expiry_and_permissions_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = auth.WorkspaceClientStore(directory)
            with self.assertRaises(auth.ClientAuthError):
                store.request_pairing("device", ["workspace", "runner"])
            with mock.patch.object(auth, "_now", return_value=1000):
                requested = store.request_pairing("device", ["workspace"])
            with mock.patch.object(auth, "_now", return_value=1600):
                with self.assertRaisesRegex(auth.ClientAuthError, "expired"):
                    store.poll(requested["pairing_id"], requested["polling_secret"])


class SSHKeyManagementTests(unittest.TestCase):
    @staticmethod
    def public_key(comment="agent key"):
        key_type = b"ssh-ed25519"
        blob = len(key_type).to_bytes(4, "big") + key_type + bytes(range(32))
        return "ssh-ed25519 %s %s" % (
            base64.b64encode(blob).decode("ascii"),
            comment,
        )

    def test_api_keys_are_isolated_from_user_authorized_keys(self):
        with tempfile.TemporaryDirectory() as home:
            ssh = Path(home, ".ssh")
            ssh.mkdir(mode=0o700)
            user_file = ssh / "authorized_keys"
            user_file.write_text("# user-managed options stay untouched\n", encoding="utf-8")
            user_file.chmod(0o600)
            store = SSHKeyStore(home)
            created = store.add(self.public_key())
            self.assertTrue(created["created"])
            self.assertEqual(store.list()["keys"][0]["fingerprint"], created["key"]["fingerprint"])
            self.assertEqual(user_file.read_text(encoding="utf-8"), "# user-managed options stay untouched\n")
            managed = ssh / "vibestack_authorized_keys"
            self.assertEqual(stat.S_IMODE(managed.stat().st_mode), 0o600)
            store.remove(created["key"]["id"])
            self.assertEqual(store.list(), {"keys": []})

    def test_invalid_private_or_multiline_material_is_rejected(self):
        with tempfile.TemporaryDirectory() as home:
            store = SSHKeyStore(home)
            for value in ("-----BEGIN OPENSSH PRIVATE KEY-----", self.public_key() + "\nextra"):
                with self.assertRaises(SSHKeyError):
                    store.add(value)

    def test_exact_persistent_ssh_link_is_allowed_but_other_links_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root, "home")
            persistent = Path(root, "data", "ssh")
            home.mkdir()
            persistent.mkdir(parents=True, mode=0o700)
            Path(home, ".ssh").symlink_to(persistent)
            store = SSHKeyStore(str(home), str(persistent))
            self.assertTrue(store.add(self.public_key())["created"])
            self.assertTrue(Path(persistent, "vibestack_authorized_keys").is_file())

        with tempfile.TemporaryDirectory() as root:
            home = Path(root, "home")
            unexpected = Path(root, "unexpected")
            expected = Path(root, "data", "ssh")
            home.mkdir()
            unexpected.mkdir(mode=0o700)
            Path(home, ".ssh").symlink_to(unexpected)
            with self.assertRaisesRegex(SSHKeyError, "safety check"):
                SSHKeyStore(str(home), str(expected)).add(self.public_key())


class CustomHostTests(unittest.TestCase):
    def test_explicit_hosts_generate_literal_bounded_nginx_rules(self):
        configured = hosts.configured_hosts("work.example.test,192.0.2.20,2001:db8::1")
        rendered = hosts.nginx_map(configured)
        self.assertIn(r"work\.example\.test", rendered)
        self.assertIn(r"\[2001:db8::1\]", rendered)
        self.assertNotIn("default 1", rendered)

    def test_invalid_host_configuration_is_rejected(self):
        for value in ("https://example.test", "bad host", "example.test:443", "127.000.0.1"):
            with self.assertRaises(ValueError, msg=value):
                hosts.configured_hosts(value)


if __name__ == "__main__":
    unittest.main()
