from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin" / "vibestack-api-token"


class TokenHelperTests(unittest.TestCase):
    def run_helper(self, command: str, token_path: Path):
        environment = dict(os.environ)
        environment["AUTOMATION_TOKEN_FILE"] = str(token_path)
        return subprocess.run(
            [sys.executable, str(HELPER), command],
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_ensure_does_not_print_secret_and_show_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            token_path = Path(temporary) / "state" / "automation.token"
            ensured = self.run_helper("ensure", token_path)
            self.assertEqual(0, ensured.returncode, ensured.stderr)
            self.assertEqual(str(token_path), ensured.stdout.strip())
            token = token_path.read_text(encoding="ascii").strip()
            self.assertEqual(43, len(token))
            self.assertNotIn(token, ensured.stdout)
            self.assertEqual(0o600, token_path.stat().st_mode & 0o777)

            shown = self.run_helper("show", token_path)
            self.assertEqual(token, shown.stdout.strip())
            rotated = self.run_helper("rotate", token_path)
            self.assertEqual(0, rotated.returncode, rotated.stderr)
            self.assertNotEqual(token, rotated.stdout.strip())
            self.assertEqual(rotated.stdout.strip(), token_path.read_text().strip())

    def test_parent_symlink_is_not_followed_for_custom_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            linked = root / "linked"
            linked.symlink_to(outside, target_is_directory=True)
            result = self.run_helper("ensure", linked / "automation.token")
            self.assertNotEqual(0, result.returncode)
            self.assertFalse((outside / "automation.token").exists())


if __name__ == "__main__":
    unittest.main()
