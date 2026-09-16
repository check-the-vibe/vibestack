"""Strict validation and cross-process transaction tests for setup state."""

from __future__ import annotations

import importlib.util
import io
import json
from importlib.machinery import SourceFileLoader
import multiprocessing
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "setup"
sys.path.insert(0, str(SETUP))
import setuplib as lib  # noqa: E402


def load_script(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup_server = load_script("vibestack_setup_state_tests", SETUP / "server.py")
setup_cli = load_script(
    "vibestack_setup_state_cli_tests", ROOT / "bin" / "vibestack-setup"
)


CATALOG = {
    "components": [
        {"id": "node", "requires": [], "probe": "node --version"},
        {"id": "cli", "requires": ["node"], "probe": "cli --version"},
    ]
}


def _record_failed_component(component, gate):
    gate.wait(10)
    lib.record_install_outcome([component], [], command_succeeded=False)


def _hold_install_job_lock(ready, release):
    lock_fd = lib.acquire_install_job_lock(blocking=False)
    try:
        ready.set()
        release.wait(10)
    finally:
        lib.release_install_job_lock(lock_fd)


class SetupStateValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_state_dir = lib.STATE_DIR
        self.old_state_path = lib.STATE_PATH
        lib.STATE_DIR = self.directory.name
        lib.STATE_PATH = str(Path(self.directory.name) / "setup.json")

    def test_legacy_editor_selection_is_read_without_resetting_saved_state(self):
        value = lib.default_state()
        value["selected"] = ["browser-editor", "node"]
        self.write_json(value)
        original = self.state_path.read_bytes()
        actual = lib.load_state()
        self.assertEqual(actual["selected"], ["node"])
        self.assertEqual(actual["auto_restore"], value["auto_restore"])
        self.assertEqual(self.state_path.read_bytes(), original)
        self.assertEqual(lib.unknown_for_state(CATALOG, actual), [])

    def tearDown(self):
        lib.STATE_DIR = self.old_state_dir
        lib.STATE_PATH = self.old_state_path
        self.directory.cleanup()

    @property
    def state_path(self):
        return Path(lib.STATE_PATH)

    def write_json(self, value):
        self.state_path.write_text(json.dumps(value), encoding="utf-8")
        self.state_path.chmod(0o600)

    def write_raw(self, value):
        self.state_path.write_bytes(value)
        self.state_path.chmod(0o600)

    def assert_state_error(self, code):
        with self.assertRaises(lib.StateError) as raised:
            lib.load_state()
        self.assertEqual(code, raised.exception.code)

    def test_absent_state_is_distinct_from_invalid_state(self):
        self.assertEqual(lib.default_state(), lib.load_state())
        lock_path = Path(lib.STATE_DIR) / lib.STATE_LOCK_NAME
        info = lock_path.stat()
        self.assertTrue(stat.S_ISREG(info.st_mode))
        self.assertEqual(0o600, stat.S_IMODE(info.st_mode))

        self.write_raw(b'{"version":1')
        self.assert_state_error("state_invalid")

    def test_production_default_uses_canonical_persistence_not_home_symlink(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIBESTACK_STATE_DIR", None)
            default_lib = load_script(
                "vibestack_setuplib_default_path_tests", SETUP / "setuplib.py"
            )
        self.assertEqual("/data/vibestack", default_lib.STATE_DIR)
        self.assertEqual("/data/vibestack/setup.json", default_lib.STATE_PATH)

        root = Path(self.directory.name)
        canonical = root / "data" / "vibestack"
        canonical.mkdir(parents=True)
        canonical.chmod(0o700)
        home = root / "home" / "vibe"
        home.mkdir(parents=True)
        (home / ".vibestack").symlink_to(canonical)
        lib.STATE_DIR = str(canonical)
        lib.STATE_PATH = str(canonical / "setup.json")

        expected = lib.mark_complete(["node"], skipped=False)
        self.assertEqual(expected, lib.load_state())
        self.assertEqual(
            expected,
            json.loads((home / ".vibestack" / "setup.json").read_text("utf-8")),
        )

    def test_unreadable_state_is_reported(self):
        lib.mark_complete([], skipped=True)
        real_open = lib.os.open

        def deny_state(path, *args, **kwargs):
            if path == "setup.json":
                raise PermissionError("denied for test")
            return real_open(path, *args, **kwargs)

        with mock.patch.object(lib.os, "open", side_effect=deny_state):
            self.assert_state_error("state_unreadable")

    def test_future_version_is_not_silently_normalized(self):
        state = lib.default_state()
        state["version"] = 2
        self.write_json(state)
        before = self.state_path.read_bytes()
        self.assert_state_error("state_version_unsupported")
        with self.assertRaises(lib.StateError) as raised:
            lib.mark_complete([], skipped=True)
        self.assertEqual("state_version_unsupported", raised.exception.code)
        self.assertEqual(before, self.state_path.read_bytes())

    def test_malformed_fields_fail_closed(self):
        valid = lib.default_state()
        cases = []
        for key, value in (
            ("completed", "yes"),
            ("auto_restore", 1),
            ("selected", ["node", "node"]),
            ("selected", ["not_valid"]),
            ("completed_at", "2026-99-99T99:99:99Z"),
        ):
            state = dict(valid)
            state[key] = value
            if key == "completed_at":
                state["completed"] = True
            cases.append(state)
        extra = dict(valid)
        extra["unexpected"] = True
        cases.append(extra)

        for state in cases:
            with self.subTest(state=state):
                self.write_json(state)
                self.assert_state_error("state_invalid")

    def test_symlink_state_and_lock_are_rejected(self):
        target = Path(self.directory.name) / "target"
        target.write_text("{}", encoding="utf-8")
        target.chmod(0o600)
        self.state_path.symlink_to(target)
        self.assert_state_error("state_unreadable")
        self.state_path.unlink()

        lock_path = Path(lib.STATE_DIR) / lib.STATE_LOCK_NAME
        lock_path.unlink()
        lock_path.symlink_to(target)
        self.assert_state_error("state_unreadable")

    def test_special_state_file_is_rejected_without_blocking(self):
        os.mkfifo(self.state_path, 0o600)
        self.assert_state_error("state_unreadable")

    def test_special_lock_files_are_rejected_without_blocking(self):
        state_lock = Path(lib.STATE_DIR) / lib.STATE_LOCK_NAME
        os.mkfifo(state_lock, 0o600)
        self.assert_state_error("state_unreadable")
        state_lock.unlink()

        job_lock = Path(lib.STATE_DIR) / lib.INSTALL_JOB_LOCK_NAME
        os.mkfifo(job_lock, 0o600)
        with self.assertRaises(lib.StateError) as raised:
            lib.acquire_install_job_lock(blocking=False)
        self.assertEqual("state_unreadable", raised.exception.code)

    def test_unknown_selected_ids_remain_unresolved_but_are_not_installed(self):
        state = lib.mark_complete(["node", "removed"], skipped=False)
        with mock.patch.object(lib, "is_installed", return_value=False):
            self.assertEqual(
                ["node", "removed"], lib.missing_for_state(CATALOG, state)
            )
            self.assertEqual(
                ["node"], lib.restorable_missing_for_state(CATALOG, state)
            )
        self.assertEqual(["removed"], lib.unknown_for_state(CATALOG, state))

        with (
            mock.patch.object(setup_server.lib, "load_state", return_value=state),
            mock.patch.object(setup_server.lib, "load_catalog", return_value=CATALOG),
            mock.patch.object(
                setup_server.lib,
                "restorable_missing_for_state",
                return_value=["node"],
            ),
            mock.patch.object(
                setup_server.lib, "unknown_for_state", return_value=["removed"]
            ),
            mock.patch.object(setup_server, "start_job", return_value=True) as start,
            mock.patch.object(setup_server, "log_line"),
        ):
            setup_server.auto_restore()
        start.assert_called_once_with(["node"], phase="restore")

    def test_arm64_catalog_disables_amd64_apps_and_filters_presets(self):
        source = json.loads((SETUP / "catalog.json").read_text("utf-8"))
        declared = {
            component["id"]: component["architectures"]
            for component in source["components"]
        }
        self.assertEqual(["amd64"], declared["chrome"])
        self.assertEqual(["amd64"], declared["chatgpt"])
        for component_id in set(declared) - {"chrome", "chatgpt"}:
            self.assertEqual(["amd64", "arm64"], declared[component_id])
        catalog = lib.catalog_for_runtime(
            source,
            architecture="arm64",
            runtime_capabilities={"nested-sandbox"},
        )
        components = lib.by_id(catalog)

        self.assertEqual("arm64", catalog["architecture"])
        self.assertTrue(components["node"]["supported"])
        self.assertIn("Supported on arm64", components["node"]["support_reason"])
        for component_id in ("chrome", "chatgpt"):
            self.assertFalse(components[component_id]["supported"])
            self.assertIn("Unavailable on arm64", components[component_id]["support_reason"])

        presets = {preset["id"]: preset for preset in catalog["presets"]}
        self.assertNotIn("chrome", presets["recommended"]["components"])
        self.assertEqual(
            ["chrome"], presets["recommended"]["unsupported_components"]
        )
        self.assertNotIn("chrome", presets["everything"]["components"])
        self.assertNotIn("chatgpt", presets["everything"]["components"])
        self.assertEqual(
            ["chrome", "chatgpt"],
            presets["everything"]["unsupported_components"],
        )

        state = lib.mark_complete(["chrome"], skipped=False)
        with mock.patch.object(lib, "is_installed") as probe:
            self.assertEqual(["chrome"], lib.missing_for_state(catalog, state))
            self.assertEqual([], lib.restorable_missing_for_state(catalog, state))
        probe.assert_not_called()
        self.assertEqual(["chrome"], lib.unsupported_for_state(catalog, state))

    def test_flatpak_requires_a_verified_runtime_capability(self):
        source = json.loads((SETUP / "catalog.json").read_text("utf-8"))
        confined = lib.catalog_for_runtime(
            source,
            architecture="amd64",
            runtime_capabilities=set(),
        )
        enabled = lib.catalog_for_runtime(
            source,
            architecture="amd64",
            runtime_capabilities={"nested-sandbox"},
        )
        confined_flatpak = lib.by_id(confined)["flatpak"]
        enabled_flatpak = lib.by_id(enabled)["flatpak"]
        self.assertFalse(confined_flatpak["supported"])
        self.assertIn("started with --flatpak", confined_flatpak["support_reason"])
        self.assertTrue(enabled_flatpak["supported"])
        self.assertEqual([], confined["runtime_capabilities"])
        self.assertEqual(["nested-sandbox"], enabled["runtime_capabilities"])

        marker = os.stat_result(
            (stat.S_IFREG | 0o444, 1, 1, 1, 0, 0, 0, 0, 0, 0)
        )
        with mock.patch.object(lib.os, "stat", return_value=marker):
            self.assertEqual(
                frozenset({"nested-sandbox"}),
                lib.current_runtime_capabilities(),
            )
        with (
            mock.patch.dict(os.environ, {"VIBESTACK_FLATPAK_ENABLED": "1"}),
            mock.patch.object(lib.os, "stat", side_effect=FileNotFoundError),
        ):
            self.assertEqual(frozenset(), lib.current_runtime_capabilities())

    def test_cross_process_install_outcomes_do_not_lose_selected_ids(self):
        context = multiprocessing.get_context("fork")
        gate = context.Event()
        components = ["component-%02d" % index for index in range(8)]
        processes = [
            context.Process(target=_record_failed_component, args=(component, gate))
            for component in components
        ]
        for process in processes:
            process.start()
        gate.set()
        for process in processes:
            process.join(15)
            self.assertEqual(0, process.exitcode)

        self.assertEqual(components, lib.load_state()["selected"])
        self.assertEqual([], list(Path(lib.STATE_DIR).glob(".setup-*.tmp")))

    def test_cross_process_installer_lease_rejects_cli_reset_and_skip(self):
        expected = lib.mark_complete(["node"], skipped=False)
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        release = context.Event()
        process = context.Process(
            target=_hold_install_job_lock, args=(ready, release)
        )
        process.start()
        try:
            self.assertTrue(ready.wait(5))
            with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                self.assertEqual(1, setup_cli.cmd_reset())
                self.assertEqual(1, setup_cli.cmd_skip())
            self.assertEqual(expected, lib.load_state())
            with self.assertRaises(lib.StateError) as raised:
                lib.acquire_install_job_lock(blocking=False)
            self.assertEqual("job_running", raised.exception.code)
        finally:
            release.set()
            process.join(10)
        self.assertEqual(0, process.exitcode)

        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, setup_cli.cmd_reset())
        self.assertEqual(lib.default_state(), lib.load_state())

    def test_install_job_probe_observes_external_owner_without_releasing_it(self):
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        release = context.Event()
        process = context.Process(
            target=_hold_install_job_lock, args=(ready, release)
        )
        process.start()
        try:
            self.assertTrue(ready.wait(5))
            self.assertTrue(lib.install_job_lock_held())
            # Merely observing the busy lease must not unlock its owner.
            with self.assertRaises(lib.StateError) as raised:
                lib.acquire_install_job_lock(blocking=False)
            self.assertEqual("job_running", raised.exception.code)
        finally:
            release.set()
            process.join(10)
        self.assertEqual(0, process.exitcode)
        self.assertFalse(lib.install_job_lock_held())

    def test_auto_restore_defers_during_external_install_instead_of_crashing(self):
        state = lib.mark_complete(["node"], skipped=False)
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        release = context.Event()
        process = context.Process(
            target=_hold_install_job_lock, args=(ready, release)
        )
        process.start()
        try:
            self.assertTrue(ready.wait(5))
            with setup_server._lock:
                setup_server._job.update(running=False, phase="idle", target=[])
            with (
                mock.patch.object(setup_server.lib, "load_state", return_value=state),
                mock.patch.object(setup_server.lib, "load_catalog", return_value=CATALOG),
                mock.patch.object(
                    setup_server.lib,
                    "restorable_missing_for_state",
                    return_value=["node"],
                ),
                mock.patch.object(
                    setup_server.lib, "unknown_for_state", return_value=[]
                ),
                mock.patch.object(
                    setup_server.lib, "unsupported_for_state", return_value=[]
                ),
                mock.patch.object(setup_server, "log_line") as log,
            ):
                setup_server.auto_restore()
            log.assert_called_once_with(
                "[setup] restore deferred: another installer holds the setup lease"
            )
            self.assertTrue(lib.install_job_lock_held())
            with self.assertRaises(lib.StateError) as raised:
                lib.acquire_install_job_lock(blocking=False)
            self.assertEqual("job_running", raised.exception.code)
        finally:
            release.set()
            process.join(10)
        self.assertEqual(0, process.exitcode)

    def test_skip_environment_does_not_bypass_external_install_lease_on_restart(self):
        expected = lib.load_state()
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        release = context.Event()
        process = context.Process(
            target=_hold_install_job_lock, args=(ready, release)
        )
        process.start()
        fake_server = mock.Mock()
        try:
            self.assertTrue(ready.wait(5))
            with (
                mock.patch.dict(os.environ, {"VIBESTACK_SKIP_SETUP": "1"}),
                mock.patch.object(setup_server, "auto_restore") as restore,
                mock.patch.object(
                    setup_server, "ThreadingHTTPServer", return_value=fake_server
                ),
                mock.patch.object(setup_server.lib, "mark_complete") as complete,
                redirect_stdout(io.StringIO()),
            ):
                setup_server.main()
            restore.assert_called_once_with()
            fake_server.serve_forever.assert_called_once_with()
            complete.assert_not_called()
            self.assertTrue(lib.install_job_lock_held())
        finally:
            release.set()
            process.join(10)
        self.assertEqual(0, process.exitcode)
        self.assertEqual(expected, lib.load_state())


if __name__ == "__main__":
    unittest.main()
