"""Hermetic contracts for the secret-free client installer."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "cli.sh"


FAKE_UNAME = """#!/bin/sh
case "$1" in
  -s) printf '%s\\n' "$FAKE_UNAME_SYSTEM" ;;
  -m) printf '%s\\n' "$FAKE_UNAME_MACHINE" ;;
  *) exit 2 ;;
esac
"""


FAKE_CURL = """#!/bin/sh
if [ "$1" = "--version" ]; then printf 'curl 8.4.0 fixture\\n'; exit 0; fi
output=
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) output=$2; shift 2 ;;
    http*) url=$1; shift ;;
    *) shift ;;
  esac
done
printf '%s\\n' "$url" >> "$FAKE_URL_LOG"
case "$FAKE_CURL_FAILURE:$url" in
  binary:*sha256) ;;
  binary:*) exit 22 ;;
  checksum:*sha256) exit 22 ;;
esac
case "$url" in
  *.sha256) /bin/cp "$FAKE_CHECKSUM" "$output" ;;
  *) /bin/cp "$FAKE_BINARY" "$output" ;;
esac
"""


class ClientInstallerTests(unittest.TestCase):
    def fixture(self, system="Linux", machine="x86_64"):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        fake_bin = root / "fake-bin"
        fake_bin.mkdir()
        (fake_bin / "uname").write_text(FAKE_UNAME, encoding="utf-8")
        (fake_bin / "curl").write_text(FAKE_CURL, encoding="utf-8")
        (fake_bin / "uname").chmod(0o755)
        (fake_bin / "curl").chmod(0o755)
        binary = root / "release-binary"
        binary.write_bytes(b"#!/bin/sh\nprintf 'fixture cli\\n'\n")
        checksum = root / "release-checksum"
        checksum.write_text(hashlib.sha256(binary.read_bytes()).hexdigest() + "  asset\n", encoding="ascii")
        log = root / "urls"
        install = root / "install"
        env = {
            **os.environ,
            "HOME": str(root / "home"),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "FAKE_UNAME_SYSTEM": system,
            "FAKE_UNAME_MACHINE": machine,
            "FAKE_BINARY": str(binary),
            "FAKE_CHECKSUM": str(checksum),
            "FAKE_URL_LOG": str(log),
            "FAKE_CURL_FAILURE": "",
            "VIBESTACK_INSTALL_DIR": str(install),
            "VIBESTACK_RELEASE_BASE": "https://releases.example/vibestack",
        }
        return directory, root, install, log, env

    def run_installer(self, env, *args):
        return subprocess.run(
            ["/bin/sh", str(INSTALLER), *args],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )

    def test_linux_install_is_atomic_and_prints_path_and_secret_free_next_step(self):
        directory, _root, install, log, env = self.fixture()
        with directory:
            result = self.run_installer(env, "--version", "0.2.0", "--server", "https://workspace.example")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(b"#!/bin/sh\nprintf 'fixture cli\\n'\n", (install / "vibestack").read_bytes())
            self.assertEqual(0o755, (install / "vibestack").stat().st_mode & 0o777)
            self.assertIn("Add %s to PATH" % install, result.stdout)
            self.assertIn("--url 'https://workspace.example'", result.stdout)
            self.assertNotIn("token", result.stdout.lower())
            urls = log.read_text(encoding="utf-8")
            self.assertIn("/v0.2.0/vibestack_0.2.0_linux_amd64", urls)
            self.assertFalse(any(path.name.startswith(".vibestack.") for path in install.iterdir()))

    def test_macos_arm64_selects_the_published_asset_and_existing_path_needs_no_edit(self):
        directory, _root, install, log, env = self.fixture("Darwin", "arm64")
        with directory:
            install.mkdir()
            env["PATH"] = f"{env['PATH']}:{install}"
            result = self.run_installer(env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("/v0.3.0/vibestack_0.3.0_darwin_arm64", log.read_text(encoding="utf-8"))
            self.assertNotIn("shell profile", result.stdout)

    def test_download_and_checksum_failures_preserve_an_existing_installation(self):
        for failure in ("binary", "checksum"):
            with self.subTest(failure=failure):
                directory, _root, install, _log, env = self.fixture()
                with directory:
                    install.mkdir()
                    target = install / "vibestack"
                    target.write_bytes(b"known-good-existing")
                    env["FAKE_CURL_FAILURE"] = failure
                    result = self.run_installer(env)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(b"known-good-existing", target.read_bytes())

                directory, _root, install, _log, env = self.fixture()
                with directory:
                    install.mkdir()
                    target = install / "vibestack"
                    target.write_bytes(b"known-good-existing")
                    Path(env["FAKE_CHECKSUM"]).write_text("0" * 64 + "  asset\n", encoding="ascii")
                    result = self.run_installer(env)
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn("existing installation was preserved", result.stderr)
                    self.assertEqual(b"known-good-existing", target.read_bytes())


if __name__ == "__main__":
    unittest.main()
