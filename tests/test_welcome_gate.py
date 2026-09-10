"""Behavioral regression tests for the interactive first-run banner."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "vibestack-welcome"


class WelcomeGateTests(unittest.TestCase):
    def run_welcome(
        self,
        *,
        setup_complete: bool,
        password_configured: bool | None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_dir = root / "home" / ".vibestack"
            state_dir.mkdir(parents=True)
            if setup_complete:
                (state_dir / "setup.json").write_text(
                    '{"completed": true, "skipped": true}\n', encoding="utf-8"
                )

            fake_bin = root / "bin"
            fake_bin.mkdir()
            sudo = fake_bin / "sudo"
            sudo.write_text(
                """#!/usr/bin/env bash
[[ "$#" -eq 3 ]] || exit 64
[[ "$1" == "-n" ]] || exit 64
[[ "$2" == "/usr/local/bin/vibestack-password" ]] || exit 64
[[ "$3" == "status" ]] || exit 64
case "${WELCOME_PASSWORD_STATUS:-error}" in
  configured) printf '%s\\n' '{"password_configured":true}' ;;
  locked) printf '%s\\n' '{"password_configured":false}' ;;
  *) exit 1 ;;
esac
""",
                encoding="utf-8",
            )
            sudo.chmod(sudo.stat().st_mode | stat.S_IXUSR)

            environment = os.environ.copy()
            environment["HOME"] = str(root / "home")
            environment["PATH"] = "%s:%s" % (fake_bin, environment["PATH"])
            if password_configured is True:
                environment["WELCOME_PASSWORD_STATUS"] = "configured"
            elif password_configured is False:
                environment["WELCOME_PASSWORD_STATUS"] = "locked"
            else:
                environment["WELCOME_PASSWORD_STATUS"] = "error"

            return subprocess.run(
                [str(SCRIPT), "--if-pending"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

    def test_completed_setup_and_configured_password_suppress_banner(self) -> None:
        result = self.run_welcome(setup_complete=True, password_configured=True)
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_setup_skip_with_locked_password_remains_pending(self) -> None:
        result = self.run_welcome(setup_complete=True, password_configured=False)
        self.assertEqual(0, result.returncode)
        self.assertIn("set your Linux password", result.stdout)
        self.assertIn("/setup/", result.stdout)

    def test_incomplete_setup_remains_pending_with_configured_password(self) -> None:
        result = self.run_welcome(setup_complete=False, password_configured=True)
        self.assertEqual(0, result.returncode)
        self.assertIn("/setup/", result.stdout)

    def test_password_status_failure_fails_closed(self) -> None:
        result = self.run_welcome(setup_complete=True, password_configured=None)
        self.assertEqual(0, result.returncode)
        self.assertIn("/setup/", result.stdout)


if __name__ == "__main__":
    unittest.main()
