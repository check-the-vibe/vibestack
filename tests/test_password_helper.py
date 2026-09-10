"""Security and persistence tests for the root-only password helper."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "vibestack-password"
LOADER = importlib.machinery.SourceFileLoader("vibestack_password", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
password_lib = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(password_lib)

VALID_HASH = (
    b"$6$rounds=656000$abcdefghijklmnop$"
    + b"A" * 86
)
OLD_HASH = (
    b"$6$rounds=656000$qrstuvwxyzABCDEF$"
    + b"B" * 86
)


class PasswordHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / ".vibestack-auth-v1"
        self.state.mkdir(mode=0o700)
        self.state.chmod(0o700)
        self.uid = os.getuid()
        self.gid = os.getgid()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def read_hash(self):
        return password_lib.read_hash(
            str(self.state), expected_uid=self.uid, expected_gid=self.gid
        )

    def write_hash(self, value=VALID_HASH):
        password_lib.write_hash(
            value,
            str(self.state),
            expected_uid=self.uid,
            expected_gid=self.gid,
        )

    def test_hash_round_trips_as_one_root_private_regular_file(self) -> None:
        self.assertIsNone(self.read_hash())
        self.write_hash()

        target = self.state / password_lib.HASH_NAME
        self.assertEqual(VALID_HASH + b"\n", target.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(target.stat().st_mode))
        self.assertEqual(1, target.stat().st_nlink)
        self.assertEqual(VALID_HASH, self.read_hash())
        self.assertEqual([target], list(self.state.iterdir()))

    def test_hash_file_symlink_and_hard_link_fail_closed(self) -> None:
        sentinel = self.root / "sentinel"
        sentinel.write_bytes(VALID_HASH + b"\n")
        sentinel.chmod(0o600)
        before = sentinel.read_bytes()

        target = self.state / password_lib.HASH_NAME
        target.symlink_to(sentinel)
        with self.assertRaises(password_lib.PasswordError):
            self.read_hash()
        self.assertEqual(before, sentinel.read_bytes())

        target.unlink()
        os.link(sentinel, target)
        with self.assertRaises(password_lib.PasswordError):
            self.read_hash()
        self.assertEqual(before, sentinel.read_bytes())

    def test_state_directory_requires_exact_owner_mode_and_no_symlink(self) -> None:
        self.state.chmod(0o750)
        with self.assertRaises(password_lib.PasswordError):
            self.read_hash()
        self.state.chmod(0o700)

        external = self.root / "external"
        external.mkdir()
        self.state.rmdir()
        self.state.symlink_to(external, target_is_directory=True)
        with self.assertRaises((password_lib.PasswordError, OSError)):
            self.read_hash()
        self.assertEqual([], list(external.iterdir()))

    def test_password_policy_is_bounded_utf8_without_control_characters(self) -> None:
        self.assertEqual(
            "correct horse battery staple".encode(),
            password_lib.validate_password("correct horse battery staple"),
        )
        for value in (
            "too short",
            " " * 12,
            "valid length\n",
            "x" * (password_lib.MAX_PASSWORD_BYTES + 1),
            123,
        ):
            with self.subTest(value=repr(value)):
                with self.assertRaises(password_lib.PasswordPolicyError):
                    password_lib.validate_password(value)

    def test_sha512_crypt_hashing_keeps_plaintext_off_argv_and_stderr(self) -> None:
        secret = b"do not expose this password"
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=VALID_HASH + b"\n", stderr=b""
        )
        observed_input = []

        def record_input(*_args, **kwargs):
            observed_input.append(bytes(kwargs["input"]))
            return completed

        with mock.patch.object(
            password_lib.subprocess, "run", side_effect=record_input
        ) as run:
            result = password_lib.hash_password(secret)

        self.assertEqual(VALID_HASH, result)
        argv = run.call_args.args[0]
        self.assertEqual(password_lib.OPENSSL, argv[0])
        self.assertIn("-6", argv)
        self.assertIn("rounds=656000$", argv[-1])
        self.assertNotIn(secret.decode(), " ".join(argv))
        self.assertEqual([secret + b"\n"], observed_input)
        self.assertEqual(
            b"\x00" * (len(secret) + 1), bytes(run.call_args.kwargs["input"])
        )
        self.assertEqual(subprocess.DEVNULL, run.call_args.kwargs["stderr"])

    def test_set_persists_only_hash_and_updates_shadow_through_stdin(self) -> None:
        secret = "this is a private sudo password"
        account_update = subprocess.CompletedProcess(args=[], returncode=0)
        with (
            mock.patch.object(password_lib, "hash_password", return_value=VALID_HASH),
            mock.patch.object(
                password_lib.subprocess, "run", return_value=account_update
            ) as run,
            mock.patch.object(
                password_lib, "read_live_hash", side_effect=[b"!", VALID_HASH]
            ),
        ):
            password_lib.set_password(
                secret,
                str(self.state),
                expected_uid=self.uid,
                expected_gid=self.gid,
            )

        self.assertEqual(VALID_HASH + b"\n", (self.state / password_lib.HASH_NAME).read_bytes())
        argv = run.call_args.args[0]
        self.assertEqual([password_lib.CHPASSWD, "--encrypted"], argv)
        self.assertNotIn(secret, " ".join(argv))
        self.assertEqual(
            b"vibe:" + VALID_HASH + b"\n", run.call_args.kwargs["input"]
        )
        self.assertNotIn(secret.encode(), (self.state / password_lib.HASH_NAME).read_bytes())

    def test_restore_locks_before_configuration_and_applies_saved_hash(self) -> None:
        with (
            mock.patch.object(password_lib, "lock_account") as lock,
            mock.patch.object(password_lib, "apply_hash") as apply,
            mock.patch.object(password_lib, "read_live_hash", return_value=b"!"),
        ):
            configured = password_lib.restore_password(
                str(self.state),
                expected_uid=self.uid,
                expected_gid=self.gid,
            )
        self.assertFalse(configured)
        lock.assert_called_once_with()
        apply.assert_not_called()

        self.write_hash()
        with (
            mock.patch.object(password_lib, "lock_account") as lock,
            mock.patch.object(password_lib, "apply_hash") as apply,
            mock.patch.object(
                password_lib, "read_live_hash", return_value=VALID_HASH
            ),
        ):
            configured = password_lib.restore_password(
                str(self.state),
                expected_uid=self.uid,
                expected_gid=self.gid,
            )
        self.assertTrue(configured)
        apply.assert_called_once_with(VALID_HASH)
        lock.assert_not_called()

    def test_set_request_has_exact_bounded_schema(self) -> None:
        secret = "schema-valid password"
        request = io.BytesIO(json.dumps({"password": secret}).encode())
        self.assertEqual(secret, password_lib.read_set_request(request))
        for raw in (
            b'{"password":"one","password":"two"}',
            b'{"password":"valid password","extra":true}',
            b"[]",
            b"x" * (password_lib.MAX_REQUEST_BYTES + 1),
        ):
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(password_lib.PasswordPolicyError):
                    password_lib.read_set_request(io.BytesIO(raw))

    def test_failures_and_status_output_never_include_hash_or_plaintext(self) -> None:
        secret = "do not echo this failure secret"
        with mock.patch.object(
            password_lib.subprocess,
            "run",
            side_effect=OSError(secret),
        ):
            with self.assertRaises(password_lib.PasswordError) as raised:
                password_lib.hash_password(secret.encode())
        self.assertNotIn(secret, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

        output = io.StringIO()
        with mock.patch.object(password_lib.sys, "stdout", output):
            password_lib._emit_status(True)
        payload = output.getvalue()
        self.assertEqual({"password_configured": True}, json.loads(payload))
        self.assertNotIn("$6$", payload)

    def test_live_shadow_reader_requires_one_safe_vibe_entry(self) -> None:
        shadow = self.root / "shadow"
        shadow.write_bytes(
            b"root:*:1:0:99999:7:::\n"
            + b"vibe:"
            + VALID_HASH
            + b":1:0:99999:7:::\n"
        )
        shadow.chmod(0o640)
        self.assertEqual(
            VALID_HASH,
            password_lib.read_live_hash(str(shadow), expected_uid=self.uid),
        )

        shadow.chmod(0o644)
        with self.assertRaises(password_lib.PasswordError):
            password_lib.read_live_hash(str(shadow), expected_uid=self.uid)

        shadow.chmod(0o640)
        shadow.write_bytes(
            b"vibe:!:1:0:99999:7:::\nvibe:*:1:0:99999:7:::\n"
        )
        with self.assertRaises(password_lib.PasswordError):
            password_lib.read_live_hash(str(shadow), expected_uid=self.uid)

    def test_status_fails_closed_for_crash_or_manual_shadow_mismatch(self) -> None:
        with mock.patch.object(password_lib, "read_live_hash", return_value=b"!"):
            self.assertFalse(
                password_lib.password_status(
                    str(self.state), expected_uid=self.uid, expected_gid=self.gid
                )
            )

        self.write_hash()
        with mock.patch.object(
            password_lib, "read_live_hash", return_value=VALID_HASH
        ):
            self.assertTrue(
                password_lib.password_status(
                    str(self.state), expected_uid=self.uid, expected_gid=self.gid
                )
            )
        for live_hash in (b"!", OLD_HASH, b""):
            with self.subTest(live_hash=live_hash[:2]):
                with (
                    mock.patch.object(
                        password_lib, "read_live_hash", return_value=live_hash
                    ),
                    self.assertRaises(password_lib.PasswordError),
                ):
                    password_lib.password_status(
                        str(self.state),
                        expected_uid=self.uid,
                        expected_gid=self.gid,
                    )

    def test_set_failure_rolls_live_back_before_persistent_state(self) -> None:
        self.write_hash(OLD_HASH)
        events = []
        original_write_hash = password_lib.write_hash

        def write_hash(value, *args, **kwargs):
            events.append(("write", value))
            return original_write_hash(value, *args, **kwargs)

        def apply_hash(value):
            events.append(("apply", value))
            if value == VALID_HASH:
                raise password_lib.PasswordError("injected account update failure")

        with (
            mock.patch.object(password_lib, "hash_password", return_value=VALID_HASH),
            mock.patch.object(password_lib, "read_live_hash", return_value=OLD_HASH),
            mock.patch.object(password_lib, "write_hash", side_effect=write_hash),
            mock.patch.object(password_lib, "apply_hash", side_effect=apply_hash),
            self.assertRaises(password_lib.PasswordError),
        ):
            password_lib.set_password(
                "this password is only for fault injection",
                str(self.state),
                expected_uid=self.uid,
                expected_gid=self.gid,
            )

        self.assertEqual(
            [
                ("write", VALID_HASH),
                ("apply", VALID_HASH),
                ("apply", OLD_HASH),
                ("write", OLD_HASH),
            ],
            events,
        )
        self.assertEqual(OLD_HASH, self.read_hash())

    def test_failed_persistence_rollback_remains_detectably_inconsistent(self) -> None:
        self.write_hash(OLD_HASH)
        live_hash = OLD_HASH
        write_calls = 0
        original_write_hash = password_lib.write_hash

        def apply_hash(value):
            nonlocal live_hash
            live_hash = value

        def read_live_hash():
            return live_hash

        def write_hash(value, *args, **kwargs):
            nonlocal write_calls
            write_calls += 1
            if write_calls == 2:
                raise OSError("injected durable rollback failure")
            return original_write_hash(value, *args, **kwargs)

        def mismatched_after_new_hash(saved_hash):
            if saved_hash == VALID_HASH:
                raise password_lib.PasswordError("injected verification failure")
            if saved_hash != live_hash:
                raise password_lib.PasswordError("injected mismatch")

        with (
            mock.patch.object(password_lib, "hash_password", return_value=VALID_HASH),
            mock.patch.object(password_lib, "read_live_hash", side_effect=read_live_hash),
            mock.patch.object(password_lib, "write_hash", side_effect=write_hash),
            mock.patch.object(password_lib, "apply_hash", side_effect=apply_hash),
            mock.patch.object(
                password_lib, "_require_live_hash", side_effect=mismatched_after_new_hash
            ),
            self.assertRaises(password_lib.PasswordError),
        ):
            password_lib.set_password(
                "this password is only for rollback fault injection",
                str(self.state),
                expected_uid=self.uid,
                expected_gid=self.gid,
            )

        self.assertEqual(VALID_HASH, self.read_hash())
        self.assertEqual(OLD_HASH, live_hash)
        with (
            mock.patch.object(password_lib, "read_live_hash", return_value=live_hash),
            self.assertRaises(password_lib.PasswordError),
        ):
            password_lib.password_status(
                str(self.state), expected_uid=self.uid, expected_gid=self.gid
            )


if __name__ == "__main__":
    unittest.main()
