"""Adversarial checks for the root-only filesystem bootstrap boundary."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "vibestack-bootstrap"
LOADER = importlib.machinery.SourceFileLoader("vibestack_bootstrap", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
bootstrap_lib = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(bootstrap_lib)


def snapshot(path: Path) -> tuple[bytes, int, int, int, int]:
    info = path.stat()
    return (
        path.read_bytes(),
        stat.S_IMODE(info.st_mode),
        info.st_uid,
        info.st_gid,
        info.st_nlink,
    )


class BootstrapSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.run = self.root / "run"
        self.data.mkdir()
        (self.data / ".vibestack-state-v1").mkdir()
        (self.data / ".vibestack-state-v1").chmod(0o755)
        self.run.mkdir()
        self.uid = os.getuid()
        self.gid = os.getgid()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def bootstrap(self) -> None:
        bootstrap_lib.bootstrap(
            data_root=str(self.data),
            run_root=str(self.run),
            root_uid=self.uid,
            vibe_uid=self.uid,
            vibe_gid=self.gid,
        )

    def assert_mode(self, path: Path, expected: int) -> None:
        self.assertEqual(expected, stat.S_IMODE(path.stat().st_mode), str(path))

    def make_sentinel(self) -> Path:
        external = self.root / "external"
        external.mkdir(exist_ok=True)
        sentinel = external / "sentinel"
        sentinel.write_bytes(b"do not touch\n")
        sentinel.chmod(0o604)
        return sentinel

    def test_bootstrap_creates_owned_bounded_log_and_runtime_layout(self) -> None:
        self.bootstrap()

        log_root = self.data / "logs" / "vibestack"
        self.assert_mode(self.data, 0o1770)
        password_state = self.data / bootstrap_lib.PASSWORD_STATE_DIR
        self.assertTrue(password_state.is_dir())
        self.assertFalse(password_state.is_symlink())
        self.assert_mode(password_state, 0o700)
        self.assertEqual((self.uid, self.gid), (password_state.stat().st_uid, password_state.stat().st_gid))
        self.assert_mode(self.data / "logs", 0o750)
        self.assert_mode(log_root, 0o1770)
        self.assert_mode(log_root / "services", 0o750)
        self.assert_mode(log_root / "nginx", 0o750)
        self.assert_mode(log_root / "desktop", 0o750)
        for name in bootstrap_lib.SERVICE_LOGS:
            target = log_root / "services" / name
            self.assertTrue(target.is_file())
            self.assertEqual(1, target.stat().st_nlink)
            self.assert_mode(target, 0o640)
        for target in (
            log_root / "nginx" / "access.jsonl",
            log_root / "nginx" / "error.log",
            log_root / "supervisord.log",
            log_root / "automation-audit.jsonl",
        ):
            self.assertTrue(target.is_file())
            self.assertEqual(1, target.stat().st_nlink)
            self.assert_mode(target, 0o640)

        runtime_root = self.run / "vibestack"
        self.assert_mode(runtime_root, 0o1770)
        self.assert_mode(runtime_root / "runtime", 0o700)
        self.assert_mode(runtime_root / "Xauthority", 0o640)
        self.assertTrue((runtime_root / "Xauthority").is_file())
        self.assertEqual(1, (runtime_root / "Xauthority").stat().st_nlink)

    def test_missing_state_marker_fails_before_data_metadata_changes(self) -> None:
        marker = self.data / ".vibestack-state-v1"
        marker.rmdir()
        self.data.chmod(0o751)
        before = self.data.stat()

        with self.assertRaises(bootstrap_lib.BootstrapError):
            self.bootstrap()

        after = self.data.stat()
        self.assertEqual(stat.S_IMODE(before.st_mode), stat.S_IMODE(after.st_mode))
        self.assertEqual((before.st_uid, before.st_gid), (after.st_uid, after.st_gid))
        self.assertFalse((self.data / "logs").exists())

    def test_symlinked_state_marker_is_not_followed(self) -> None:
        sentinel = self.make_sentinel()
        marker = self.data / ".vibestack-state-v1"
        marker.rmdir()
        marker.symlink_to(sentinel.parent, target_is_directory=True)
        before = snapshot(sentinel)
        data_mode = stat.S_IMODE(self.data.stat().st_mode)

        with self.assertRaises(bootstrap_lib.BootstrapError):
            self.bootstrap()

        self.assertEqual(before, snapshot(sentinel))
        self.assertEqual(data_mode, stat.S_IMODE(self.data.stat().st_mode))
        self.assertFalse((self.data / "logs").exists())

    def test_symlinked_log_components_never_touch_external_sentinel(self) -> None:
        cases = ("logs", "log-root", "services", "service-leaf")
        for case in cases:
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    data = root / "data"
                    run = root / "run"
                    external = root / "external"
                    data.mkdir()
                    (data / ".vibestack-state-v1").mkdir()
                    (data / ".vibestack-state-v1").chmod(0o755)
                    run.mkdir()
                    external.mkdir()
                    sentinel = external / "sentinel"
                    sentinel.write_bytes(b"do not touch\n")
                    sentinel.chmod(0o604)
                    before = snapshot(sentinel)

                    if case == "logs":
                        (data / "logs").symlink_to(external, target_is_directory=True)
                    else:
                        (data / "logs").mkdir()
                        if case == "log-root":
                            (data / "logs" / "vibestack").symlink_to(
                                external, target_is_directory=True
                            )
                        else:
                            stack = data / "logs" / "vibestack"
                            stack.mkdir()
                            if case == "services":
                                (stack / "services").symlink_to(
                                    external, target_is_directory=True
                                )
                            else:
                                services = stack / "services"
                                services.mkdir()
                                (services / "x11vnc.log").symlink_to(sentinel)

                    with self.assertRaises((bootstrap_lib.BootstrapError, OSError)):
                        bootstrap_lib.bootstrap(
                            data_root=str(data),
                            run_root=str(run),
                            root_uid=os.getuid(),
                            vibe_uid=os.getuid(),
                            vibe_gid=os.getgid(),
                        )
                    self.assertEqual(before, snapshot(sentinel))

    def test_planted_password_state_is_never_adopted_or_followed(self) -> None:
        sentinel = self.make_sentinel()
        password_state = self.data / bootstrap_lib.PASSWORD_STATE_DIR
        password_state.symlink_to(sentinel.parent, target_is_directory=True)
        before = snapshot(sentinel)

        with self.assertRaises((bootstrap_lib.BootstrapError, OSError)):
            self.bootstrap()

        self.assertEqual(before, snapshot(sentinel))
        self.assertTrue(password_state.is_symlink())

    def test_existing_password_state_with_open_permissions_fails_closed(self) -> None:
        password_state = self.data / bootstrap_lib.PASSWORD_STATE_DIR
        password_state.mkdir(mode=0o755)
        password_state.chmod(0o755)

        with self.assertRaises(bootstrap_lib.BootstrapError):
            self.bootstrap()

        self.assert_mode(password_state, 0o755)

    def test_hard_linked_audit_fails_closed(self) -> None:
        sentinel = self.make_sentinel()
        stack = self.data / "logs" / "vibestack"
        stack.mkdir(parents=True)
        os.link(sentinel, stack / "automation-audit.jsonl")
        before = snapshot(sentinel)

        with self.assertRaises(bootstrap_lib.BootstrapError):
            self.bootstrap()
        self.assertEqual(before, snapshot(sentinel))

    def test_special_service_leaf_fails_closed_without_blocking(self) -> None:
        services = self.data / "logs" / "vibestack" / "services"
        services.mkdir(parents=True)
        os.mkfifo(services / "x11vnc.log")
        with self.assertRaises(bootstrap_lib.BootstrapError):
            self.bootstrap()

    def test_restart_removes_runtime_symlinks_without_following_them(self) -> None:
        sentinel = self.make_sentinel()
        external = sentinel.parent
        runtime = self.run / "vibestack"
        runtime.mkdir()
        (runtime / "Xauthority").symlink_to(sentinel)
        (runtime / "runtime").symlink_to(external, target_is_directory=True)
        before = snapshot(sentinel)

        self.bootstrap()

        self.assertEqual(before, snapshot(sentinel))
        self.assertFalse((self.run / "vibestack" / "runtime").is_symlink())
        self.assertTrue((self.run / "vibestack" / "runtime").is_dir())
        self.assertFalse((self.run / "vibestack" / "Xauthority").is_symlink())
        self.assertTrue((self.run / "vibestack" / "Xauthority").is_file())

    def test_restart_replaces_runtime_root_symlink_without_following_it(self) -> None:
        sentinel = self.make_sentinel()
        (self.run / "vibestack").symlink_to(
            sentinel.parent, target_is_directory=True
        )
        before = snapshot(sentinel)

        self.bootstrap()

        self.assertEqual(before, snapshot(sentinel))
        self.assertFalse((self.run / "vibestack").is_symlink())
        self.assertTrue((self.run / "vibestack").is_dir())


if __name__ == "__main__":
    unittest.main()
