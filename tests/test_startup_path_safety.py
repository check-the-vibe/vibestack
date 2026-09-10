"""Host launcher tests for destructive /data bind-mount rejection."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StartupPathSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "workspace" / "vibestack"
        self.repo.mkdir(parents=True)
        self.script = self.repo / "startup.sh"
        shutil.copy2(ROOT / "startup.sh", self.script)
        self.script.chmod(0o755)
        self.home = self.root / "home"
        self.home.mkdir()
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.docker_log = self.root / "docker.log"
        docker = self.fake_bin / "docker"
        docker.write_text(
            """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$DOCKER_LOG"
if [[ "$1" == "ps" ]]; then
  if [[ "${RESTORE_TEST_EXISTING:-}" == "1" ]]; then
    echo "$VIBESTACK_CONTAINER"
    awk '$1 == "rename" {print $3}' "$DOCKER_LOG" 2>/dev/null || true
  fi
  exit 0
fi
if [[ "$1" == "inspect" && "${2:-}" == "--format" ]]; then
  echo healthy
fi
if [[ "$1" == "exec" && "$*" == *"setup/api/state"* ]]; then
  echo "${RESTORE_TEST_STATUS:-not-required}"
fi
exit 0
""",
            encoding="utf-8",
        )
        docker.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment.update(
            PATH=f"{self.fake_bin}:{self.environment['PATH']}",
            HOME=str(self.home),
            DOCKER_LOG=str(self.docker_log),
            VIBESTACK_IMAGE="vibestack:path-test",
            VIBESTACK_CONTAINER="vibestack-path-test",
        )
        self.environment.pop("VIBESTACK_DATA", None)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_startup(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.script), *arguments],
            cwd=self.repo,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_rejected_before_side_effects(
        self, data: Path | str, *, projects: Path | None = None
    ) -> None:
        prospective_projects = projects or self.root / (
            "uncreated-projects-%d" % len(list(self.root.iterdir()))
        )
        result = self.run_startup(
            "--data",
            str(data),
            "--projects",
            str(prospective_projects),
            "--adopt-data",
        )
        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertIn("Unsafe data directory", result.stderr)
        self.assertFalse(prospective_projects.exists())
        self.assertFalse(self.docker_log.exists())

    def assert_projects_rejected_before_side_effects(
        self, projects: Path | str, *, suffix: str
    ) -> None:
        data = self.root / f"uncreated-safe-state-{suffix}"
        result = self.run_startup(
            "--data", str(data), "--projects", str(projects), "--adopt-data"
        )
        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertIn("Unsafe projects directory", result.stderr)
        self.assertFalse(data.exists())
        self.assertFalse(self.docker_log.exists())

    def test_root_home_repo_and_repo_ancestor_are_rejected(self) -> None:
        for data in (Path("/"), self.home, self.repo, self.repo.parent):
            with self.subTest(data=data):
                self.assert_rejected_before_side_effects(data)

    def test_system_top_level_directories_are_rejected_even_with_adoption(self) -> None:
        for data in (Path("/tmp"), Path("/var"), Path("/opt"), Path("/mnt")):
            with self.subTest(data=data):
                self.assert_rejected_before_side_effects(data)

    def test_system_and_credential_descendants_are_rejected_before_adoption(self) -> None:
        (self.home / ".ssh").mkdir()
        (self.home / ".gnupg").mkdir()
        (self.repo / ".git").mkdir()
        paths = (
            Path("/etc/vibestack-not-state"),
            Path("/usr/local"),
            Path("/var/lib/vibestack-not-state"),
            self.home / ".ssh",
            self.home / ".ssh" / "nested",
            self.home / ".gnupg",
            self.home / ".git-credentials",
            self.repo / ".git",
        )
        for data in paths:
            with self.subTest(data=data):
                self.assert_rejected_before_side_effects(data)

    def test_credential_ancestor_is_rejected_before_adoption(self) -> None:
        keyrings = self.home / ".local" / "share" / "keyrings"
        keyrings.mkdir(parents=True)
        self.assert_rejected_before_side_effects(self.home / ".local" / "share")

    def test_symlink_and_dotdot_aliases_of_repo_are_rejected(self) -> None:
        alias = self.root / "repo-alias"
        alias.symlink_to(self.repo, target_is_directory=True)
        self.assert_rejected_before_side_effects(alias)
        self.assert_rejected_before_side_effects(self.repo / "not-created" / "..")

    def test_data_and_projects_must_not_be_the_same_directory(self) -> None:
        target = self.root / "same-target"
        self.assert_rejected_before_side_effects(target, projects=target)
        self.assertFalse(target.exists())

    def test_broad_or_vibestack_source_projects_paths_are_rejected(self) -> None:
        alias = self.root / "projects-repo-alias"
        alias.symlink_to(self.repo, target_is_directory=True)
        paths = (
            Path("/"),
            Path("/tmp"),
            Path("/var"),
            Path("/opt"),
            self.home,
            self.repo,
            alias,
            self.repo / "not-created" / "..",
        )
        for index, projects in enumerate(paths):
            with self.subTest(projects=projects):
                self.assert_projects_rejected_before_side_effects(
                    projects, suffix=f"broad-{index}"
                )

    def test_system_credential_and_git_metadata_projects_are_rejected(self) -> None:
        keyrings = self.home / ".local" / "share" / "keyrings"
        keyrings.mkdir(parents=True)
        (self.home / ".ssh").mkdir()
        (self.home / ".gnupg").mkdir()
        (self.repo / ".git").mkdir()
        other_metadata = self.root / "other-repository" / ".git"
        other_metadata.mkdir(parents=True)
        paths = (
            Path("/etc/vibestack-not-projects"),
            Path("/usr/local/vibestack-not-projects"),
            Path("/var/lib/vibestack-not-projects"),
            self.home / ".ssh",
            self.home / ".ssh" / "nested",
            self.home / ".gnupg",
            self.home / ".local" / "share",
            self.repo / ".git",
            self.repo / ".git" / "objects",
            other_metadata,
            other_metadata / "objects",
        )
        for index, projects in enumerate(paths):
            with self.subTest(projects=projects):
                self.assert_projects_rejected_before_side_effects(
                    projects, suffix=f"sensitive-{index}"
                )

    def test_default_and_new_dedicated_directories_are_initialized(self) -> None:
        result = self.run_startup()
        self.assertEqual(0, result.returncode, result.stderr)
        default_data = self.repo.parent / "vibestack-data"
        self.assertTrue((default_data / ".vibestack-state-v1").is_dir())
        self.assertTrue((default_data / "projects").is_dir())
        calls = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("build -t vibestack:path-test", calls)
        self.assertIn("run -d", calls)

        self.docker_log.unlink()
        data = self.root / "new-state"
        projects = self.root / "new-projects"
        result = self.run_startup("--data", str(data), "--projects", str(projects))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((data / ".vibestack-state-v1").is_dir())
        self.assertTrue(projects.is_dir())
        self.assertTrue(self.docker_log.exists())

    def test_flatpak_security_options_require_explicit_mode(self) -> None:
        default = self.run_startup(
            "--data", str(self.root / "default-state"),
            "--projects", str(self.root / "default-projects"),
        )
        self.assertEqual(0, default.returncode, default.stderr)
        default_calls = self.docker_log.read_text(encoding="utf-8")
        self.assertNotIn("seccomp=unconfined", default_calls)
        self.assertNotIn("VIBESTACK_FLATPAK_ENABLED=1", default_calls)

        self.docker_log.unlink()
        enabled = self.run_startup(
            "--flatpak",
            "--data", str(self.root / "flatpak-state"),
            "--projects", str(self.root / "flatpak-projects"),
        )
        self.assertEqual(0, enabled.returncode, enabled.stderr)
        enabled_calls = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("-e VIBESTACK_FLATPAK_ENABLED=1", enabled_calls)
        self.assertIn("--security-opt seccomp=unconfined", enabled_calls)
        self.assertIn("--security-opt apparmor=unconfined", enabled_calls)
        self.assertIn("--security-opt systempaths=unconfined", enabled_calls)
        self.assertNotIn("--privileged", enabled_calls)
        self.assertNotIn("--cap-add", enabled_calls)

    def test_existing_unmarked_directory_requires_explicit_adoption(self) -> None:
        data = self.root / "existing-state"
        projects = self.root / "existing-projects"
        data.mkdir()

        rejected = self.run_startup(
            "--data", str(data), "--projects", str(projects)
        )
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("existing directory is unmarked", rejected.stderr)
        self.assertFalse(projects.exists())
        self.assertFalse(self.docker_log.exists())

        adopted = self.run_startup(
            "--data",
            str(data),
            "--projects",
            str(projects),
            "--adopt-data",
        )
        self.assertEqual(0, adopted.returncode, adopted.stderr)
        self.assertTrue((data / ".vibestack-state-v1").is_dir())
        self.assertTrue(self.docker_log.exists())

    def test_adoption_rejects_unrelated_content_but_accepts_known_state(self) -> None:
        unrelated = self.root / "personal-files"
        unrelated.mkdir()
        (unrelated / "holiday-photo.jpg").write_bytes(b"not VibeStack state")
        projects = self.root / "personal-projects"

        rejected = self.run_startup(
            "--data", str(unrelated), "--projects", str(projects), "--adopt-data"
        )
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("non-VibeStack entry", rejected.stderr)
        self.assertFalse((unrelated / ".vibestack-state-v1").exists())
        self.assertFalse(projects.exists())
        self.assertFalse(self.docker_log.exists())

        known = self.root / "known-state"
        known.mkdir()
        for name in ("bash_history", "claude.json", "gitconfig"):
            (known / name).touch()
        for name in (
            ".vibestack-auth-v1",
            "chatgpt",
            "chrome",
            "claude",
            "claude-desktop",
            "codex",
            "flatpak",
            "flatpak-apps",
            "godot-config",
            "godot-data",
            "keyrings",
            "logs",
            "opencode",
            "opencode-config",
            "projects",
            "vibestack",
        ):
            (known / name).mkdir()
        accepted_projects = self.root / "known-projects"
        accepted = self.run_startup(
            "--data",
            str(known),
            "--projects",
            str(accepted_projects),
            "--adopt-data",
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertTrue((known / ".vibestack-state-v1").is_dir())
        self.assertTrue(self.docker_log.exists())

    def test_adoption_rejects_known_names_with_unsafe_types(self) -> None:
        cases = ("directory-as-file", "file-as-directory", "symlink")
        for index, case in enumerate(cases):
            with self.subTest(case=case):
                data = self.root / f"wrong-type-{index}"
                data.mkdir()
                if case == "directory-as-file":
                    (data / "claude.json").mkdir()
                elif case == "file-as-directory":
                    (data / "chrome").touch()
                else:
                    (data / "target").mkdir()
                    (data / "codex").symlink_to("target", target_is_directory=True)
                    # The otherwise-unknown target would also be rejected, but
                    # the sorted directory traversal is not part of the contract.
                    (data / "target").rename(data / "opencode")
                    (data / "codex").unlink()
                    (data / "codex").symlink_to("opencode", target_is_directory=True)
                projects = self.root / f"wrong-type-projects-{index}"
                result = self.run_startup(
                    "--data",
                    str(data),
                    "--projects",
                    str(projects),
                    "--adopt-data",
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn("unsafe type", result.stderr)
                self.assertFalse((data / ".vibestack-state-v1").exists())
                self.assertFalse(projects.exists())
                self.assertFalse(self.docker_log.exists())

    def test_failed_saved_component_restore_fails_the_candidate(self) -> None:
        self.environment["RESTORE_TEST_STATUS"] = "failed:removed-browser-id"
        self.environment["RESTORE_TEST_EXISTING"] = "1"
        data = self.root / "restore-state"
        projects = self.root / "restore-projects"

        result = self.run_startup("--data", str(data), "--projects", str(projects))

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "Saved component restoration failed (removed-browser-id)", result.stderr
        )
        calls = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("logs --tail 200 vibestack-path-test", calls)
        rollback_match = re.search(
            r"rename vibestack-path-test (vibestack-path-test-rollback-[^\s]+)",
            calls,
        )
        self.assertIsNotNone(rollback_match, calls)
        rollback = rollback_match.group(1)
        self.assertIn("rm -f vibestack-path-test", calls)
        self.assertIn(f"rename {rollback} vibestack-path-test", calls)
        self.assertIn("start vibestack-path-test", calls)

    def test_invalid_or_unsupported_saved_state_fails_immediately(self) -> None:
        statuses = (
            "failed:state-state_invalid",
            "failed:state-state_unreadable",
            "failed:state-state_version_unsupported",
            "failed:state-response-invalid",
        )
        for index, status in enumerate(statuses):
            with self.subTest(status=status):
                self.environment["RESTORE_TEST_STATUS"] = status
                data = self.root / f"invalid-state-{index}"
                projects = self.root / f"invalid-projects-{index}"

                result = self.run_startup(
                    "--data", str(data), "--projects", str(projects)
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    f"Saved component restoration failed ({status[7:]})",
                    result.stderr,
                )
                self.assertNotIn("still restoring", result.stdout)

    def test_restore_probe_requires_explicit_valid_state_envelope(self) -> None:
        source = self.script.read_text(encoding="utf-8")
        self.assertIn('payload.get("state_valid") is not True', source)
        self.assertIn('payload.get("state_error") is not None', source)
        self.assertIn('payload.get("unknown_selected")', source)
        self.assertIn('fail("state-response-invalid")', source)
        for code in (
            "state_invalid",
            "state_unreadable",
            "state_version_unsupported",
        ):
            self.assertIn(code, source)

    def test_restore_probe_drops_privileges_and_python_user_state(self) -> None:
        result = self.run_startup()
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.docker_log.read_text(encoding="utf-8")
        self.assertIn(
            "exec -u vibe -w / vibestack-path-test /usr/bin/env -i "
            "HOME=/home/vibe USER=vibe LOGNAME=vibe PATH=/usr/bin:/bin "
            "LANG=C LC_ALL=C /usr/bin/python3 -I -c",
            calls,
        )


if __name__ == "__main__":
    unittest.main()
