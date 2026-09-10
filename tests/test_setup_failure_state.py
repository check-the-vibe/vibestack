"""Regression tests for setup install completion and retry state."""

from __future__ import annotations

import importlib.util
import io
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
import tempfile
import unittest
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


setup_server = load_script("vibestack_setup_server_tests", SETUP / "server.py")
setup_cli = load_script("vibestack_setup_cli_tests", ROOT / "bin" / "vibestack-setup")


CATALOG = {
    "components": [
        {"id": "node", "requires": []},
        {"id": "cli", "requires": ["node"]},
    ]
}


class FakeProcess:
    def __init__(self, returncode: int):
        self.returncode = returncode
        self.stdout = io.BytesIO(b"installer output\n")

    def wait(self):
        return self.returncode


class SetupFailureStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_state_dir = lib.STATE_DIR
        self.old_state_path = lib.STATE_PATH
        lib.STATE_DIR = self.directory.name
        lib.STATE_PATH = str(Path(self.directory.name) / "setup.json")
        with setup_server._lock:
            setup_server._job.update(
                running=True,
                log=b"",
                log_base=0,
                ok=None,
                target=["node", "cli"],
                phase="install",
            )

    def tearDown(self):
        lib.STATE_DIR = self.old_state_dir
        lib.STATE_PATH = self.old_state_path
        self.directory.cleanup()

    def test_web_failure_keeps_full_request_and_does_not_complete(self):
        with (
            mock.patch.object(setup_server.lib, "load_catalog", return_value=CATALOG),
            mock.patch.object(setup_server.lib, "installed_ids", return_value=["node"]),
            mock.patch.object(setup_server.subprocess, "Popen", return_value=FakeProcess(1)),
        ):
            setup_server._run_job(["node", "cli"], "install")

        state = lib.load_state()
        self.assertFalse(state["completed"])
        self.assertEqual(["cli", "node"], state["selected"])
        self.assertFalse(setup_server._job["ok"])

    def test_zero_exit_without_probe_convergence_is_still_a_failure(self):
        with (
            mock.patch.object(setup_server.lib, "load_catalog", return_value=CATALOG),
            mock.patch.object(setup_server.lib, "installed_ids", return_value=["node"]),
            mock.patch.object(setup_server.subprocess, "Popen", return_value=FakeProcess(0)),
        ):
            setup_server._run_job(["node", "cli"], "install")

        self.assertFalse(lib.load_state()["completed"])
        self.assertFalse(setup_server._job["ok"])

    def test_cli_failure_keeps_dependencies_and_does_not_complete(self):
        with (
            mock.patch.object(setup_cli.lib, "load_catalog", return_value=CATALOG),
            mock.patch.object(setup_cli.lib, "installed_ids", return_value=["node"]),
            mock.patch.object(setup_cli.subprocess, "call", return_value=1),
        ):
            result = setup_cli.cmd_install(["cli"])

        state = lib.load_state()
        self.assertEqual(1, result)
        self.assertFalse(state["completed"])
        self.assertEqual(["cli", "node"], state["selected"])

    def test_failure_while_adding_preserves_prior_completion_for_restore(self):
        lib.mark_complete(["node"], skipped=False)
        state, converged = lib.record_install_outcome(
            ["cli"], ["node"], command_succeeded=False
        )
        self.assertFalse(converged)
        self.assertTrue(state["completed"])
        self.assertFalse(state["skipped"])
        self.assertEqual(["cli", "node"], state["selected"])


if __name__ == "__main__":
    unittest.main()
