"""Exercise the persistence script without changing host ownership."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "vibestack-persist"


class PersistenceOwnershipTests(unittest.TestCase):
    def test_user_state_is_linked_without_touching_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            fake_bin = root / "bin"
            runtime_docs = root / "runtime-docs"
            projects = data / "projects"
            home.mkdir()
            projects.mkdir(parents=True)
            fake_bin.mkdir()
            runtime_docs.mkdir()
            (runtime_docs / "AGENTS.md").write_text("default agent guide\n", encoding="utf-8")
            (runtime_docs / "CLAUDE.md").write_text("default claude guide\n", encoding="utf-8")
            sentinel = projects / "keep-owner.txt"
            sentinel.write_text("untouched\n", encoding="utf-8")

            (fake_bin / "mountpoint").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (fake_bin / "mountpoint").chmod(0o755)

            environment = os.environ.copy()
            environment.update(
                PATH=f"{fake_bin}:{environment['PATH']}",
                VIBESTACK_PERSIST_HOME_DIR=str(home),
                VIBESTACK_PERSIST_DATA_DIR=str(data),
                VIBESTACK_RUNTIME_DOC_DIR=str(runtime_docs),
            )
            subprocess.run(["bash", str(SCRIPT)], check=True, env=environment, capture_output=True, text=True)

            self.assertEqual("untouched\n", sentinel.read_text(encoding="utf-8"))
            self.assertFalse(sentinel.is_symlink())
            self.assertTrue((home / ".vibestack").is_symlink())
            self.assertTrue((data / "vibestack").is_dir())
            self.assertTrue((home / ".ssh").is_symlink())
            self.assertEqual(data / "ssh", (home / ".ssh").readlink())
            self.assertEqual(0o700, (data / "ssh").stat().st_mode & 0o777)
            chatgpt_profile = home / ".config" / "Codex"
            self.assertTrue(chatgpt_profile.is_symlink())
            self.assertEqual(data / "chatgpt", chatgpt_profile.readlink())
            self.assertFalse((home / ".config" / "ChatGPT").exists())
            godot_config = home / ".config" / "godot"
            godot_data = home / ".local" / "share" / "godot"
            self.assertTrue(godot_config.is_symlink())
            self.assertTrue(godot_data.is_symlink())
            self.assertEqual(data / "godot-config", godot_config.readlink())
            self.assertEqual(data / "godot-data", godot_data.readlink())
            flatpak = home / ".local" / "share" / "flatpak"
            flatpak_apps = home / ".var" / "app"
            self.assertTrue(flatpak.is_symlink())
            self.assertTrue(flatpak_apps.is_symlink())
            self.assertEqual(data / "flatpak", flatpak.readlink())
            self.assertEqual(data / "flatpak-apps", flatpak_apps.readlink())
            desktop_logs = home / "Desktop" / "VibeStack Logs"
            self.assertTrue(desktop_logs.is_symlink())
            self.assertEqual(data / "logs" / "vibestack", desktop_logs.readlink())
            agents = home / ".codex" / "AGENTS.md"
            claude = home / ".claude" / "CLAUDE.md"
            opencode = home / ".config" / "opencode" / "AGENTS.md"
            self.assertEqual("default agent guide\n", agents.read_text(encoding="utf-8"))
            self.assertEqual("default claude guide\n", claude.read_text(encoding="utf-8"))
            self.assertEqual("default agent guide\n", opencode.read_text(encoding="utf-8"))
            self.assertTrue(agents.is_symlink())
            self.assertTrue(claude.is_symlink())
            self.assertTrue(opencode.is_symlink())
            self.assertEqual(runtime_docs / "AGENTS.md", agents.readlink())
            self.assertEqual(runtime_docs / "CLAUDE.md", claude.readlink())
            self.assertEqual(runtime_docs / "AGENTS.md", opencode.readlink())

            legacy_collision = home / ".config" / "ChatGPT"
            legacy_collision.mkdir()
            (legacy_collision / "keep").write_text("user-owned\n", encoding="utf-8")
            agents.unlink()
            claude.unlink()
            opencode.unlink()
            agents.write_text("custom agent guide\n", encoding="utf-8")
            claude.write_text("custom claude guide\n", encoding="utf-8")
            opencode.write_text("custom opencode guide\n", encoding="utf-8")
            subprocess.run(["bash", str(SCRIPT)], check=True, env=environment, capture_output=True, text=True)
            self.assertEqual("custom agent guide\n", agents.read_text(encoding="utf-8"))
            self.assertEqual("custom claude guide\n", claude.read_text(encoding="utf-8"))
            self.assertEqual("custom opencode guide\n", opencode.read_text(encoding="utf-8"))
            self.assertEqual(
                "user-owned\n",
                (legacy_collision / "keep").read_text(encoding="utf-8"),
            )

            agents.unlink()
            override = home / ".codex" / "AGENTS.override.md"
            override.write_text("override agent guide\n", encoding="utf-8")
            subprocess.run(["bash", str(SCRIPT)], check=True, env=environment, capture_output=True, text=True)
            self.assertFalse(agents.exists())
            self.assertEqual("override agent guide\n", override.read_text(encoding="utf-8"))

    def test_unsafe_persistent_state_link_is_rejected_as_unprivileged_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            fake_bin = root / "bin"
            external = root / "external"
            home.mkdir()
            data.mkdir()
            fake_bin.mkdir()
            external.mkdir()
            (data / "vibestack").symlink_to(external, target_is_directory=True)
            (fake_bin / "mountpoint").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (fake_bin / "mountpoint").chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                PATH=f"{fake_bin}:{environment['PATH']}",
                VIBESTACK_PERSIST_HOME_DIR=str(home),
                VIBESTACK_PERSIST_DATA_DIR=str(data),
                VIBESTACK_RUNTIME_DOC_DIR=str(root / "missing-docs"),
            )

            result = subprocess.run(
                ["bash", str(SCRIPT)],
                check=False,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("refusing unsafe state directory: vibestack", result.stderr)
            self.assertEqual([], list(external.iterdir()))

    def test_desktop_ancestor_symlink_is_rejected_without_following_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            fake_bin = root / "bin"
            external = root / "external"
            home.mkdir()
            data.mkdir()
            fake_bin.mkdir()
            external.mkdir()
            sentinel = external / "sentinel"
            sentinel.write_text("untouched\n", encoding="utf-8")
            (home / "Desktop").symlink_to(external, target_is_directory=True)
            (fake_bin / "mountpoint").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (fake_bin / "mountpoint").chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                PATH=f"{fake_bin}:{environment['PATH']}",
                VIBESTACK_PERSIST_HOME_DIR=str(home),
                VIBESTACK_PERSIST_DATA_DIR=str(data),
                VIBESTACK_RUNTIME_DOC_DIR=str(root / "missing-docs"),
            )

            result = subprocess.run(
                ["bash", str(SCRIPT)],
                check=False,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("refusing unsafe Desktop directory", result.stderr)
            self.assertEqual("untouched\n", sentinel.read_text(encoding="utf-8"))
            self.assertEqual([sentinel], list(external.iterdir()))

    def test_wrong_desktop_log_symlink_is_replaced_without_following_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            fake_bin = root / "bin"
            external = root / "external"
            desktop = home / "Desktop"
            desktop.mkdir(parents=True)
            data.mkdir()
            fake_bin.mkdir()
            external.mkdir()
            sentinel = external / "sentinel"
            sentinel.write_text("untouched\n", encoding="utf-8")
            link = desktop / "VibeStack Logs"
            link.symlink_to(sentinel)
            (fake_bin / "mountpoint").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            (fake_bin / "mountpoint").chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                PATH=f"{fake_bin}:{environment['PATH']}",
                VIBESTACK_PERSIST_HOME_DIR=str(home),
                VIBESTACK_PERSIST_DATA_DIR=str(data),
                VIBESTACK_RUNTIME_DOC_DIR=str(root / "missing-docs"),
            )

            result = subprocess.run(
                ["bash", str(SCRIPT)],
                check=True,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual("untouched\n", sentinel.read_text(encoding="utf-8"))
            self.assertTrue(link.is_symlink())
            self.assertEqual(data / "logs" / "vibestack", link.readlink())

    def test_nonempty_chatgpt_profile_migrates_into_empty_persistent_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            fake_bin = root / "bin"
            profile = home / ".config" / "Codex"
            profile.mkdir(parents=True)
            data.mkdir()
            (data / "chatgpt").mkdir()
            legacy = home / ".config" / "ChatGPT"
            legacy.symlink_to(data / "chatgpt", target_is_directory=True)
            fake_bin.mkdir()
            (profile / "Preferences").write_text("profile-data\n", encoding="utf-8")
            (fake_bin / "mountpoint").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (fake_bin / "mountpoint").chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                PATH=f"{fake_bin}:{environment['PATH']}",
                VIBESTACK_PERSIST_HOME_DIR=str(home),
                VIBESTACK_PERSIST_DATA_DIR=str(data),
                VIBESTACK_RUNTIME_DOC_DIR=str(root / "missing-docs"),
            )

            subprocess.run(
                ["bash", str(SCRIPT)],
                check=True,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertTrue(profile.is_symlink())
            self.assertEqual(data / "chatgpt", profile.readlink())
            self.assertFalse(legacy.exists())
            self.assertFalse(legacy.is_symlink())
            self.assertEqual(
                "profile-data\n",
                (data / "chatgpt" / "Preferences").read_text(encoding="utf-8"),
            )

    def test_conflicting_chatgpt_profiles_fail_without_removing_either_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            data = root / "data"
            fake_bin = root / "bin"
            profile = home / ".config" / "Codex"
            persistent = data / "chatgpt"
            profile.mkdir(parents=True)
            persistent.mkdir(parents=True)
            fake_bin.mkdir()
            (profile / "local").write_text("local\n", encoding="utf-8")
            (persistent / "saved").write_text("saved\n", encoding="utf-8")
            (fake_bin / "mountpoint").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (fake_bin / "mountpoint").chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                PATH=f"{fake_bin}:{environment['PATH']}",
                VIBESTACK_PERSIST_HOME_DIR=str(home),
                VIBESTACK_PERSIST_DATA_DIR=str(data),
                VIBESTACK_RUNTIME_DOC_DIR=str(root / "missing-docs"),
            )

            result = subprocess.run(
                ["bash", str(SCRIPT)],
                check=False,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("refusing conflicting state directory: chatgpt", result.stderr)
            self.assertEqual("local\n", (profile / "local").read_text(encoding="utf-8"))
            self.assertEqual("saved\n", (persistent / "saved").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
