#!/usr/bin/env python3
"""Supply-chain and archive-safety contracts for the optional installer."""

from __future__ import annotations

import io
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = ROOT / "bin" / "vibestack-install"
CATALOG_PATH = ROOT / "setup" / "catalog.json"
DOC_PATH = ROOT / "docs" / "research" / "installer-supply-chain.md"
ARCHIVE_ROOT = "node-v22.23.2-linux-x64"


def installer_source() -> str:
    return INSTALLER_PATH.read_text(encoding="utf-8")


def validator_source() -> str:
    source = installer_source()
    begin = "# NODE_ARCHIVE_VALIDATOR_BEGIN\n"
    end = "# NODE_ARCHIVE_VALIDATOR_END\n"
    if source.count(begin) != 1 or source.count(end) != 1:
        raise AssertionError("archive validator markers must occur exactly once")
    return source.split(begin, 1)[1].split(end, 1)[0]


def godot_extractor_source() -> str:
    source = installer_source()
    begin = "# GODOT_ARCHIVE_EXTRACTOR_BEGIN\n"
    end = "# GODOT_ARCHIVE_EXTRACTOR_END\n"
    if source.count(begin) != 1 or source.count(end) != 1:
        raise AssertionError("Godot archive extractor markers must occur exactly once")
    return source.split(begin, 1)[1].split(end, 1)[0]


def resolver_source() -> str:
    source = installer_source()
    begin = "# COMPONENT_RESOLVER_BEGIN\n"
    end = "# COMPONENT_RESOLVER_END\n"
    if source.count(begin) != 1 or source.count(end) != 1:
        raise AssertionError("component resolver markers must occur exactly once")
    return source.split(begin, 1)[1].split(end, 1)[0]


def bash_function(name: str) -> str:
    """Extract one top-level Bash function for unprivileged behavioral tests."""
    source = installer_source()
    match = re.search(rf"(?m)^{re.escape(name)}\(\) \{{\n", source)
    if match is None:
        raise AssertionError(f"missing Bash function: {name}")
    following = re.search(r"(?m)^[a-z_][a-z0-9_]*\(\) \{\n", source[match.end() :])
    end = len(source) if following is None else match.end() + following.start()
    return source[match.start() : end]


def shell_functions(*names: str) -> str:
    return "\n".join(bash_function(name) for name in names)


def directory(name: str, mode: int = 0o755) -> tarfile.TarInfo:
    member = tarfile.TarInfo(name)
    member.type = tarfile.DIRTYPE
    member.mode = mode
    return member


def regular(name: str, content: bytes = b"safe", mode: int = 0o644) -> tuple[tarfile.TarInfo, io.BytesIO]:
    member = tarfile.TarInfo(name)
    member.size = len(content)
    member.mode = mode
    return member, io.BytesIO(content)


def symlink(name: str, target: str) -> tarfile.TarInfo:
    member = tarfile.TarInfo(name)
    member.type = tarfile.SYMTYPE
    member.linkname = target
    member.mode = 0o777
    return member


def hardlink(name: str, target: str) -> tarfile.TarInfo:
    member = tarfile.TarInfo(name)
    member.type = tarfile.LNKTYPE
    member.linkname = target
    member.mode = 0o644
    return member


def fifo(name: str) -> tarfile.TarInfo:
    member = tarfile.TarInfo(name)
    member.type = tarfile.FIFOTYPE
    member.mode = 0o600
    return member


def godot_elf(machine: int) -> bytes:
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    header[6] = 1
    header[16:18] = (2).to_bytes(2, byteorder="little")
    header[18:20] = machine.to_bytes(2, byteorder="little")
    return bytes(header) + b"pinned-godot"


def zip_member(
    name: str, content: bytes, mode: int = stat.S_IFREG | 0o755
) -> tuple[zipfile.ZipInfo, bytes]:
    member = zipfile.ZipInfo(name)
    member.create_system = 3
    member.external_attr = mode << 16
    return member, content


class NodeArchiveValidatorTests(unittest.TestCase):
    def run_validator(self, members: list[tarfile.TarInfo | tuple[tarfile.TarInfo, io.BytesIO]]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "node.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                for value in members:
                    if isinstance(value, tuple):
                        archive.addfile(value[0], value[1])
                    else:
                        archive.addfile(value)
            return subprocess.run(
                [sys.executable, "-I", "-", str(archive_path), ARCHIVE_ROOT],
                input=validator_source(),
                text=True,
                capture_output=True,
                check=False,
            )

    def baseline(self) -> list[tarfile.TarInfo | tuple[tarfile.TarInfo, io.BytesIO]]:
        return [
            directory(ARCHIVE_ROOT),
            directory(f"{ARCHIVE_ROOT}/bin"),
            regular(f"{ARCHIVE_ROOT}/bin/node", b"ELF", 0o755),
        ]

    def test_accepts_regular_files_and_internal_links(self) -> None:
        members = self.baseline()
        members.extend(
            [
                symlink(f"{ARCHIVE_ROOT}/bin/node-link", "node"),
                symlink(f"{ARCHIVE_ROOT}/bin/node-link-chain", "node-link"),
                hardlink(
                    f"{ARCHIVE_ROOT}/bin/node-hardlink",
                    f"{ARCHIVE_ROOT}/bin/node",
                ),
            ]
        )
        result = self.run_validator(members)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_rejects_paths_links_types_modes_duplicates_and_missing_targets(self) -> None:
        bad_members = {
            "absolute path": regular("/etc/escape"),
            "parent traversal": regular(f"{ARCHIVE_ROOT}/../../escape"),
            "wrong root": regular("other-root/file"),
            "absolute symlink": symlink(f"{ARCHIVE_ROOT}/absolute", "/etc/passwd"),
            "symlink traversal": symlink(
                f"{ARCHIVE_ROOT}/bin/escape", "../../../outside"
            ),
            "hardlink traversal": hardlink(
                f"{ARCHIVE_ROOT}/bin/escape-hard", "outside"
            ),
            "fifo": fifo(f"{ARCHIVE_ROOT}/pipe"),
            "set-id mode": regular(f"{ARCHIVE_ROOT}/set-id", mode=0o4755),
            "missing link target": symlink(
                f"{ARCHIVE_ROOT}/bin/missing", "not-present"
            ),
            "duplicate member": regular(f"{ARCHIVE_ROOT}/bin/node", b"other"),
        }
        for label, bad_member in bad_members.items():
            with self.subTest(label=label):
                result = self.run_validator(self.baseline() + [bad_member])
                self.assertNotEqual(0, result.returncode)
                self.assertIn("unsafe Node.js archive:", result.stderr)

    def test_rejects_post_strip_escapes_and_invalid_link_graphs(self) -> None:
        cases = {
            # This target is root/bin/node before --strip-components=1, but
            # ../node-v.../bin/node outside the extraction root afterwards.
            "post-strip symlink escape": [
                symlink(
                    f"{ARCHIVE_ROOT}/bin/escape",
                    f"../../{ARCHIVE_ROOT}/bin/node",
                )
            ],
            "link cycle": [
                symlink(f"{ARCHIVE_ROOT}/bin/cycle-a", "cycle-b"),
                symlink(f"{ARCHIVE_ROOT}/bin/cycle-b", "cycle-a"),
            ],
            "symlink ancestor": [
                symlink(f"{ARCHIVE_ROOT}/alias", "bin"),
                regular(f"{ARCHIVE_ROOT}/alias/payload"),
            ],
            "hard link to directory": [
                hardlink(f"{ARCHIVE_ROOT}/bin/directory-hardlink", f"{ARCHIVE_ROOT}/bin")
            ],
            "hard link to symlink": [
                symlink(f"{ARCHIVE_ROOT}/bin/node-alias", "node"),
                hardlink(
                    f"{ARCHIVE_ROOT}/bin/alias-hardlink",
                    f"{ARCHIVE_ROOT}/bin/node-alias",
                ),
            ],
            "non-canonical link target": [
                symlink(f"{ARCHIVE_ROOT}/bin/non-canonical", "./node")
            ],
        }
        for label, extra_members in cases.items():
            with self.subTest(label=label):
                result = self.run_validator(self.baseline() + extra_members)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("unsafe Node.js archive:", result.stderr)


class GodotArchiveExtractorTests(unittest.TestCase):
    MEMBER = "Godot_v4.7.2-stable_linux.x86_64"

    def run_extractor(
        self,
        members: list[tuple[zipfile.ZipInfo, bytes]],
        expected_machine: int = 62,
    ) -> tuple[subprocess.CompletedProcess[str], bytes | None]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = root / "godot.zip"
            output_path = root / "godot"
            with zipfile.ZipFile(
                archive_path, mode="w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for member, content in members:
                    archive.writestr(member, content)
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-",
                    str(archive_path),
                    self.MEMBER,
                    str(expected_machine),
                    str(output_path),
                ],
                input=godot_extractor_source(),
                text=True,
                capture_output=True,
                check=False,
            )
            output = output_path.read_bytes() if output_path.exists() else None
            return result, output

    def test_accepts_one_matching_regular_elf_for_each_supported_machine(self) -> None:
        for machine in (62, 183):
            with self.subTest(machine=machine):
                payload = godot_elf(machine)
                result, output = self.run_extractor(
                    [zip_member(self.MEMBER, payload)], expected_machine=machine
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(payload, output)

    def test_rejects_wrong_shape_type_and_elf_architecture(self) -> None:
        cases = {
            "extra member": [
                zip_member(self.MEMBER, godot_elf(62)),
                zip_member("extra", b"extra"),
            ],
            "wrong name": [zip_member("other", godot_elf(62))],
            "symlink": [
                zip_member(self.MEMBER, b"target", stat.S_IFLNK | 0o777)
            ],
            "not ELF": [zip_member(self.MEMBER, b"not-an-elf-binary-at-all")],
            "wrong architecture": [zip_member(self.MEMBER, godot_elf(183))],
        }
        for label, members in cases.items():
            with self.subTest(label=label):
                result, _ = self.run_extractor(members)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("unsafe Godot archive:", result.stderr)


class InstallerPinningContractTests(unittest.TestCase):
    def test_node_download_is_official_versioned_and_hash_pinned(self) -> None:
        source = installer_source()
        self.assertIn("NODE_VERSION=22.23.2", source)
        self.assertIn("NODE_NPM_VERSION=10.9.8", source)
        self.assertIn(
            "NODE_SHA256_X64=b294a556e639d64338823920e5866c21c02741742d2e1529ee1a225c1ec9252a",
            source,
        )
        self.assertIn(
            "NODE_SHA256_ARM64=013b59cfd2819703a6f4a14ab891fc46fc2a4e3f5bcd92de3fb4929b43e35b30",
            source,
        )
        self.assertIn(
            '"https://nodejs.org/dist/v${NODE_VERSION}/${archive_name}"', source
        )
        self.assertIn("sha256sum -c -", source)
        self.assertIn("--proto '=https' --proto-redir '=https' --tlsv1.2", source)
        self.assertNotIn("deb.nodesource.com", source)
        self.assertNotRegex(source, r"curl[^\n]*\|\s*(?:sudo\s+)?bash")
        self.assertLess(
            source.index("# NODE_ARCHIVE_VALIDATOR_BEGIN"),
            source.index('tar -xzf "$archive_path"'),
        )

    def test_node_and_npm_install_paths_and_versions_are_explicit(self) -> None:
        source = installer_source()
        self.assertIn(
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            source,
        )
        self.assertIn("export NPM_CONFIG_PREFIX=/usr/local", source)
        self.assertIn('[[ "$installed_node" == "v${NODE_VERSION}" ]]', source)
        self.assertIn('[[ "$installed_npm" == "$NODE_NPM_VERSION" ]]', source)
        self.assertIn(
            'installed_npm="$(PATH="$tree/bin:$PATH" "$tree/bin/npm" --version)"',
            source,
        )
        self.assertIn("NODE_INSTALL_PARENT=/opt/vibestack", source)
        self.assertIn('mv -Tn -- "$NODE_STAGING_DIR" "$final_tree"', source)
        self.assertIn('mv -Tf -- "$NODE_CURRENT_TMPDIR/new" "$current_link"', source)
        self.assertNotIn("cp -a -- \"$NODE_STAGING_DIR", source)
        self.assertNotIn("ensure_safe_node_destination", source)
        self.assertIn("--no-same-owner", source)

    def test_agent_packages_are_exactly_pinned_and_verified(self) -> None:
        source = installer_source()
        for expected in (
            "npm_global @anthropic-ai/claude-code 2.1.263",
            "npm_global @openai/codex 0.153.4",
            "npm_global opencode-ai 1.18.29",
        ):
            self.assertIn(expected, source)
        self.assertIn("npm install -g --no-audit --no-fund --", source)
        self.assertIn('[[ "$installed_version" == "$expected_version" ]]', source)

    def test_amd64_only_apps_reject_other_architectures_before_download(self) -> None:
        source = installer_source()
        for function_name, download_message in (
            ("install_chrome", "downloading Google Chrome"),
            ("install_chatgpt", "downloading the ChatGPT desktop app"),
        ):
            start = source.index(f"{function_name}()")
            end = source.index("\n}", start)
            body = source[start:end]
            self.assertLess(body.index("require_amd64"), body.index(download_message))

    def test_catalog_reports_exact_versions_and_architecture_limits(self) -> None:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        components = {item["id"]: item for item in catalog["components"]}
        self.assertIn("22.23.2", components["node"]["name"])
        self.assertIn("npm 10.9.8", components["node"]["description"])
        self.assertIn('test "$(node --version)" = v22.23.2', components["node"]["probe"])
        self.assertIn('test "$(npm --version)" = 10.9.8', components["node"]["probe"])
        for component_id, version in (
            ("claude-code", "2.1.263"),
            ("codex-cli", "0.153.4"),
            ("opencode", "1.18.29"),
        ):
            self.assertIn(version, components[component_id]["probe"])
        self.assertIn("amd64", components["chrome"]["description"])
        self.assertIn("amd64-only", components["chatgpt"]["description"])
        self.assertEqual(["chrome"], components["chatgpt"]["requires"])
        self.assertIn("amd64/arm64", components["claude-desktop"]["description"])

    def test_build_essential_is_an_exact_allowlisted_catalog_component(self) -> None:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        components = {item["id"]: item for item in catalog["components"]}
        component = components["build-essential"]
        self.assertEqual("tools", component["group"])
        self.assertEqual(["amd64", "arm64"], component["architectures"])
        self.assertEqual([], component["requires"])
        self.assertEqual(
            "test \"$(dpkg-query -W -f='${db:Status-Abbrev}' build-essential 2>/dev/null)\" = 'ii '",
            component["probe"],
        )
        everything = next(
            preset for preset in catalog["presets"] if preset["id"] == "everything"
        )
        self.assertIn("build-essential", everything["components"])

        source = installer_source()
        self.assertIn(
            "apt_install build-essential", bash_function("install_build_essential")
        )
        self.assertRegex(
            source,
            r"(?m)^\s+build-essential\)\s+install_build_essential ;;$",
        )
        self.assertRegex(
            source,
            r"(?m)^\s+node\|[^\n]*\|build-essential\|[^\n]*\) ;;$",
        )

    def test_flatpak_is_stable_flathub_only_and_runtime_gated(self) -> None:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        components = {item["id"]: item for item in catalog["components"]}
        component = components["flatpak"]
        self.assertEqual("apps", component["group"])
        self.assertEqual(["amd64", "arm64"], component["architectures"])
        self.assertEqual(["nested-sandbox"], component["runtime_requirements"])
        self.assertIn("xdg-desktop-portal-xapp", component["probe"])
        self.assertIn("https://dl.flathub.org/repo/", component["probe"])

        body = bash_function("install_flatpak")
        self.assertIn(
            "apt_install flatpak xdg-desktop-portal xdg-desktop-portal-xapp",
            body,
        )
        self.assertIn("/run/vibestack/host/flatpak-enabled", body)
        self.assertIn("0:0:444:1", body)
        self.assertIn("/usr/sbin/runuser -u vibe --", body)
        self.assertIn("/usr/local/bin/vibestack-flatpak check", body)
        self.assertIn("/usr/local/bin/vibestack-flatpak _ensure-flathub", body)
        self.assertNotIn("gnome-software", body)

        helper = (ROOT / "bin" / "vibestack-flatpak").read_text(encoding="utf-8")
        self.assertIn(
            "readonly FLATHUB_REPO=https://dl.flathub.org/repo/flathub.flatpakrepo",
            helper,
        )
        self.assertEqual(1, helper.count("remote-add"))
        self.assertIn("--if-not-exists flathub", helper)
        self.assertIn('"${configured_url%/}" != "${FLATHUB_URL%/}"', helper)
        self.assertIn("--unshare-user --unshare-pid --unshare-uts --unshare-ipc", helper)
        self.assertIn('flatpak --user install flathub "$app_id"', helper)
        self.assertIn('remote-info --app --show-metadata flathub "$app_id"', helper)
        self.assertNotIn("remote-info --show-permissions", helper)
        self.assertNotIn("flatpak --user install --from", helper)
        self.assertIn("--connect-timeout 10 --max-time 60 --max-filesize 65536", helper)
        self.assertIn("--proto '=https'", helper)
        self.assertIn('"$actual_app_id" != "$expected_app_id"', helper)
        self.assertNotIn("sudo ", helper)
        self.assertNotIn("eval ", helper)

        rejected = subprocess.run(
            ["bash", str(ROOT / "bin" / "vibestack-flatpak"), "info", "../bad"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("Invalid Flatpak application ID", rejected.stderr)

        accepted_shape = subprocess.run(
            [
                "bash",
                str(ROOT / "bin" / "vibestack-flatpak"),
                "install-url",
                "flatpak+https://dl.flathub.org/repo/appstream/../bad.flatpakref",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, accepted_shape.returncode)
        self.assertIn("unsupported path", accepted_shape.stderr)

        for bad_url, expected_error in (
            (
                "https://dl.flathub.org/repo/appstream/org.example.App.flatpakref",
                "Only flatpak+https",
            ),
            (
                "flatpak+https://example.invalid/repo/appstream/org.example.App.flatpakref",
                "Only stable Flathub",
            ),
            (
                "flatpak+https://dl.flathub.org/repo/appstream/org.example.App.flatpakref?source=other",
                "query or fragment",
            ),
            (
                "flatpak+https://dl.flathub.org/repo/appstream/org%2eexample.App.flatpakref",
                "unsupported path",
            ),
        ):
            rejected_url = subprocess.run(
                [
                    "bash",
                    str(ROOT / "bin" / "vibestack-flatpak"),
                    "install-url",
                    bad_url,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, rejected_url.returncode)
            self.assertIn(expected_error, rejected_url.stderr)

        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "application.flatpakref"
            reference.write_text(
                "[Flatpak Ref]\n"
                "Name=org.example.App\n"
                "Branch=stable\n"
                "IsRuntime=false\n"
                "Url=https://example.invalid/repo/\n",
                encoding="utf-8",
            )
            wrong_remote = subprocess.run(
                [
                    "bash",
                    str(ROOT / "bin" / "vibestack-flatpak"),
                    "install-ref",
                    str(reference),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, wrong_remote.returncode)
            self.assertIn("Only references from", wrong_remote.stderr)

            reference.write_text(
                "[Flatpak Ref]\n"
                "Name=../bad\n"
                "Branch=stable\n"
                "IsRuntime=false\n"
                "Url=https://dl.flathub.org/repo/\n",
                encoding="utf-8",
            )
            invalid_id = subprocess.run(
                [
                    "bash",
                    str(ROOT / "bin" / "vibestack-flatpak"),
                    "install-ref",
                    str(reference),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(2, invalid_id.returncode)
            self.assertIn("Invalid Flatpak application ID", invalid_id.stderr)

            symlink = Path(directory) / "linked.flatpakref"
            symlink.symlink_to(reference)
            linked = subprocess.run(
                [
                    "bash",
                    str(ROOT / "bin" / "vibestack-flatpak"),
                    "install-ref",
                    str(symlink),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, linked.returncode)
            self.assertIn("Cannot open Flatpak reference", linked.stderr)

    def test_godot_release_is_pinned_validated_and_desktop_integrated(self) -> None:
        source = installer_source()
        self.assertIn("GODOT_VERSION=4.7.2", source)
        self.assertIn(
            "GODOT_SHA256_X64="
            "cadd3204e728a35d3f13adb7fd0d7902636b79f6b95c40c265eb73b6c35329e4",
            source,
        )
        self.assertIn(
            "GODOT_SHA256_ARM64="
            "5dd0d86405cf7e8adf79fb6377b38ba682a2846cb378ffe5364f38c01ad29b9d",
            source,
        )
        body = bash_function("install_godot")
        self.assertIn(
            '"https://github.com/godotengine/godot/releases/download/'
            '${GODOT_VERSION}-stable/${archive_name}"',
            body,
        )
        self.assertIn("Godot_v${GODOT_VERSION}-stable_linux.${godot_arch}.zip", body)
        self.assertIn("expected_machine=62", body)
        self.assertIn("expected_machine=183", body)
        self.assertLess(body.index("sha256sum -c -"), body.index("extract_godot_archive"))
        self.assertLess(body.index("extract_godot_archive"), body.index("publish_godot_install"))
        self.assertIn("desktop-file-validate", body)
        self.assertIn("Categories=Development;IDE;", body)
        self.assertIn("StartupWMClass=Godot", body)
        self.assertIn("--rendering-method gl_compatibility", body)
        publication = bash_function("publish_godot_install")
        self.assertIn("add_shortcut org.godotengine.Godot", publication)
        self.assertLess(
            publication.index('rm -f -- "$commit_path"'),
            publication.index('install -m 0755 "$source_binary"'),
        )
        self.assertLess(
            publication.index("add_shortcut org.godotengine.Godot"),
            publication.index('mv -Tf -- "$marker_tmp" "$commit_path"'),
        )
        self.assertRegex(source, r"(?m)^\s+godot\)\s+install_godot ;;$")
        self.assertRegex(source, r"(?m)^\s+node\|[^\n]*\|godot\|[^\n]*\) ;;$")

        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        components = {item["id"]: item for item in catalog["components"]}
        component = components["godot"]
        self.assertEqual("apps", component["group"])
        self.assertEqual(["amd64", "arm64"], component["architectures"])
        self.assertEqual([], component["requires"])
        self.assertIn("4.7.2", component["name"])
        self.assertIn(
            "/usr/share/applications/org.godotengine.Godot.desktop",
            component["probe"],
        )
        self.assertIn(
            "/usr/local/bin/.vibestack-godot-4.7.2.complete",
            component["probe"],
        )
        self.assertIn("= 'godot 4.7.2'", component["probe"])
        self.assertIn("^4\\.7\\.2\\.stable\\.official\\.", component["probe"])
        everything = next(
            preset for preset in catalog["presets"] if preset["id"] == "everything"
        )
        self.assertIn("godot", everything["components"])

        documentation = DOC_PATH.read_text(encoding="utf-8")
        for architecture, checksum in (
            (
                "x86_64",
                "cadd3204e728a35d3f13adb7fd0d7902636b79f6b95c40c265eb73b6c35329e4",
            ),
            (
                "arm64",
                "5dd0d86405cf7e8adf79fb6377b38ba682a2846cb378ffe5364f38c01ad29b9d",
            ),
        ):
            self.assertIn(
                "https://github.com/godotengine/godot/releases/download/"
                f"4.7.2-stable/Godot_v4.7.2-stable_linux.{architecture}.zip",
                documentation,
            )
            self.assertIn(checksum, documentation)

    def test_residual_update_risks_are_documented(self) -> None:
        documentation = DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("moving `latest` URLs", documentation)
        self.assertIn("not independently signature-verified", documentation)
        self.assertIn("lifecycle scripts", documentation)

    def test_downloads_are_bounded_and_resolver_failure_is_not_success(self) -> None:
        source = installer_source()
        self.assertIn("--connect-timeout 30", source)
        self.assertIn('--max-time "$max_seconds"', source)
        self.assertIn('--max-filesize "$max_bytes"', source)
        self.assertIn("downloaded_size <= max_bytes", source)
        self.assertIn('if ! ORDERED="$(VIBESTACK_CATALOG=', source)
        self.assertIn('say "component resolution failed"', source)
        self.assertIn('say "resolver returned unknown privileged component:', source)

    def test_privileged_resolver_rejects_unknown_original_arguments(self) -> None:
        script = resolver_source().replace(
            'sys.path.insert(0, "/usr/share/vibestack")',
            f"sys.path.insert(0, {str(ROOT / 'setup')!r})",
        )
        environment = os.environ.copy()
        environment["VIBESTACK_CATALOG"] = str(CATALOG_PATH)
        rejected = subprocess.run(
            [sys.executable, "-I", "-", "not-a-component"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(2, rejected.returncode, rejected.stderr)
        self.assertIn("unknown component(s): not-a-component", rejected.stderr)
        self.assertEqual("", rejected.stdout)

        accepted = subprocess.run(
            [sys.executable, "-I", "-", "claude-code"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual("node claude-code", accepted.stdout.strip())


class GodotPublicationBehaviorTests(unittest.TestCase):
    @staticmethod
    def make_command(path: Path, suffix: str) -> None:
        path.write_text(
            "#!/bin/sh\nprintf '%%s\\n' '4.7.2.stable.official.%s'\n" % suffix,
            encoding="utf-8",
        )
        path.chmod(0o755)

    def publication_harness(self) -> str:
        definitions = shell_functions(
            "ensure_safe_owned_directory",
            "publish_godot_install",
        )
        return f"""
set -uo pipefail
GODOT_VERSION=4.7.2
GODOT_COMMIT_PATH=/unused
INSTALL_TMPDIR="$6"
TEST_DESKTOP_ENTRY="$4"
TEST_DESKTOP_DIR="$6"
say() {{ printf '%s\\n' "$*" >&2; }}
refresh_desktop_database() {{ test "$1" = "${{TEST_DESKTOP_ENTRY%/*}}"; }}
add_shortcut() {{ install -m 0755 "$TEST_DESKTOP_ENTRY" "$TEST_DESKTOP_DIR/$1.desktop"; }}
{definitions}
publish_godot_install "$1" "$2" "$3" "$4" "$5" "$7" "$8" "$9"
"""

    def run_publication(
        self,
        source_binary: Path,
        source_entry: Path,
        binary_destination: Path,
        entry_destination: Path,
        marker: Path,
        desktop: Path,
        inject_late_failure: bool,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "/bin/bash",
                "-c",
                self.publication_harness(),
                "vibestack-godot-publication-test",
                str(source_binary),
                str(source_entry),
                str(binary_destination),
                str(entry_destination),
                str(marker),
                str(desktop),
                str(os.getuid()),
                str(os.getgid()),
                "1" if inject_late_failure else "0",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_late_failure_invalidates_convergence_and_retry_repairs_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_binary = root / "source-godot"
            source_entry = root / "source.desktop"
            self.make_command(source_binary, "new")
            source_entry.write_text("[Desktop Entry]\nName=New Godot\n", encoding="utf-8")

            public_bin = root / "usr-local-bin"
            applications = root / "applications"
            desktop = root / "Desktop"
            for directory_path in (public_bin, applications, desktop):
                directory_path.mkdir(mode=0o755)
            applications.chmod(0o775)
            binary_destination = public_bin / "godot"
            entry_destination = applications / "org.godotengine.Godot.desktop"
            marker = public_bin / ".vibestack-godot-4.7.2.complete"
            self.make_command(binary_destination, "old")
            entry_destination.write_text(
                "[Desktop Entry]\nName=Old Godot\n", encoding="utf-8"
            )
            marker.write_text("godot 4.7.2\n", encoding="utf-8")

            def converged() -> bool:
                if not marker.is_file() or not entry_destination.is_file():
                    return False
                if marker.read_text(encoding="utf-8") != "godot 4.7.2\n":
                    return False
                version = subprocess.run(
                    [binary_destination, "--version"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                return version.returncode == 0 and version.stdout.startswith(
                    "4.7.2.stable.official."
                )

            self.assertTrue(converged(), "the fixture should begin converged")

            failed = self.run_publication(
                source_binary,
                source_entry,
                binary_destination,
                entry_destination,
                marker,
                desktop,
                inject_late_failure=True,
            )
            self.assertNotEqual(0, failed.returncode)
            self.assertIn("injected Godot late publication failure", failed.stderr)
            self.assertFalse(converged(), "a failed publication must not converge")
            self.assertEqual(source_binary.read_bytes(), binary_destination.read_bytes())
            self.assertEqual(source_entry.read_bytes(), entry_destination.read_bytes())
            self.assertEqual(
                source_entry.read_bytes(),
                (desktop / "org.godotengine.Godot.desktop").read_bytes(),
            )

            for attempt in range(2):
                with self.subTest(repair_attempt=attempt + 1):
                    repaired = self.run_publication(
                        source_binary,
                        source_entry,
                        binary_destination,
                        entry_destination,
                        marker,
                        desktop,
                        inject_late_failure=False,
                    )
                    self.assertEqual(0, repaired.returncode, repaired.stderr)
                    self.assertEqual("godot 4.7.2\n", marker.read_text(encoding="utf-8"))
                    self.assertEqual(0o755, stat.S_IMODE(applications.stat().st_mode))
                    self.assertTrue(converged())


class NodePublicationBehaviorTests(unittest.TestCase):
    @staticmethod
    def make_command(path: Path, output: str) -> None:
        path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n", encoding="utf-8")
        path.chmod(0o755)

    def make_tree(self, root: Path) -> Path:
        tree = root / ARCHIVE_ROOT
        binary_directory = tree / "bin"
        binary_directory.mkdir(parents=True, mode=0o755)
        tree.chmod(0o755)
        self.make_command(binary_directory / "node", "v22.23.2")
        self.make_command(binary_directory / "npm", "10.9.8")
        (binary_directory / "npx").symlink_to("node")
        (binary_directory / "corepack").symlink_to("node")
        return tree

    def publication_harness(self) -> str:
        definitions = shell_functions(
            "remove_private_directory",
            "ensure_safe_owned_directory",
            "validate_node_tree",
            "validate_public_node_entry",
            "cleanup_node_link_directories",
            "publish_node_links",
        )
        return f"""
set -uo pipefail
NODE_VERSION=22.23.2
NODE_NPM_VERSION=10.9.8
NODE_INSTALL_PARENT=/unused
NODE_LINK_TMPDIR=""
NODE_CURRENT_TMPDIR=""
say() {{ printf '%s\\n' "$*" >&2; }}
{definitions}
publish_node_links "$1" "$2" "$3" "$4" "$5" "$6"
"""

    def run_publication(
        self, tree: Path, public_bin: Path, current_link: Path, fail_after: int
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "/bin/bash",
                "-c",
                self.publication_harness(),
                "vibestack-publication-test",
                str(tree),
                str(public_bin),
                str(current_link),
                str(os.getuid()),
                str(os.getgid()),
                str(fail_after),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_mid_publication_failure_restores_old_node_without_following_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tree = self.make_tree(root / "trees")
            public_bin = root / "usr-local" / "bin"
            public_bin.mkdir(parents=True)
            public_bin.chmod(0o755)
            current_parent = root / "opt-vibestack"
            current_parent.mkdir()
            current_parent.chmod(0o755)
            current_link = current_parent / "node-current"

            old_tree = root / "old-tree"
            (old_tree / "bin").mkdir(parents=True)
            self.make_command(old_tree / "bin" / "node", "old-node")
            self.make_command(old_tree / "bin" / "npm", "old-npm")
            (old_tree / "bin" / "npx").symlink_to("node")
            (old_tree / "bin" / "corepack").symlink_to("node")
            current_link.symlink_to(old_tree)
            for name in ("node", "npm", "npx", "corepack"):
                (public_bin / name).symlink_to(current_link / "bin" / name)
            old_node_bytes = (old_tree / "bin" / "node").read_bytes()

            unrelated_sentinel = root / "unrelated-sentinel"
            unrelated_sentinel.write_text("unchanged", encoding="utf-8")
            usr_local = root / "usr-local"
            untouched_links = (
                usr_local / "include" / "node",
                usr_local / "lib" / "node_modules",
                usr_local / "share" / "doc",
                usr_local / "README.md",
                usr_local / "LICENSE",
                usr_local / "CHANGELOG.md",
            )
            for link in untouched_links:
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(unrelated_sentinel)

            result = self.run_publication(tree, public_bin, current_link, 2)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("injected Node.js link publication failure", result.stderr)
            self.assertEqual(
                "old-node",
                subprocess.check_output([public_bin / "node"], text=True).strip(),
            )
            self.assertEqual(old_tree / "bin" / "node", (public_bin / "node").resolve())
            self.assertEqual(old_node_bytes, (old_tree / "bin" / "node").read_bytes())
            self.assertEqual("unchanged", unrelated_sentinel.read_text(encoding="utf-8"))
            for link in untouched_links:
                self.assertEqual(unrelated_sentinel, link.resolve())
            self.assertEqual(old_tree, current_link.resolve())
            self.assertFalse(any(public_bin.glob(".vibestack-node-links.*")))
            self.assertFalse(any(current_parent.glob(".node-current.*")))

    def test_success_is_idempotent_and_uses_one_current_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tree = self.make_tree(root / "trees")
            public_bin = root / "usr-local-bin"
            public_bin.mkdir()
            public_bin.chmod(0o755)
            current_parent = root / "opt-vibestack"
            current_parent.mkdir()
            current_parent.chmod(0o755)
            current_link = current_parent / "node-current"

            for attempt in range(2):
                with self.subTest(attempt=attempt + 1):
                    result = self.run_publication(tree, public_bin, current_link, 0)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(
                        "v22.23.2",
                        subprocess.check_output([public_bin / "node"], text=True).strip(),
                    )
                    self.assertEqual(
                        "10.9.8",
                        subprocess.check_output([public_bin / "npm"], text=True).strip(),
                    )
                    self.assertEqual(tree, current_link.resolve())
                    for command_name in ("node", "npm", "npx", "corepack"):
                        self.assertEqual(
                            current_link / "bin" / command_name,
                            Path(os.readlink(public_bin / command_name)),
                        )

    def test_tree_root_symlink_and_escaping_member_symlink_are_rejected(self) -> None:
        definitions = shell_functions("validate_node_tree")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            real_tree = self.make_tree(root / "trees")
            tree_link = root / "tree-link"
            tree_link.symlink_to(real_tree)
            script = f"""
NODE_VERSION=22.23.2
NODE_NPM_VERSION=10.9.8
say() {{ :; }}
{definitions}
validate_node_tree "$1" "$2" "$3"
"""
            for candidate in (tree_link, real_tree):
                if candidate == real_tree:
                    (real_tree / "escape").symlink_to(root / "outside")
                    (root / "outside").write_text("sentinel", encoding="utf-8")
                result = subprocess.run(
                    [
                        "/bin/bash",
                        "-c",
                        script,
                        "vibestack-tree-test",
                        str(candidate),
                        str(os.getuid()),
                        str(os.getgid()),
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(0, result.returncode)


class InstallerLockBehaviorTests(unittest.TestCase):
    def test_concurrent_second_invocation_is_rejected(self) -> None:
        definition = bash_function("acquire_install_lock")
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / "install.lock"
            script = f"""
INSTALL_LOCK_FD=""
INSTALL_LOCK_PATH=/unused
say() {{ printf '%s\\n' "$*" >&2; }}
{definition}
acquire_install_lock "$1" "$2" "$3" || exit 42
printf 'READY\\n'
read -r _
"""
            command = [
                "/bin/bash",
                "-c",
                script,
                "vibestack-lock-test",
                str(lock_path),
                str(os.getuid()),
                str(os.getgid()),
            ]
            first = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual("READY", first.stdout.readline().strip())
                second = subprocess.run(
                    command,
                    input="\n",
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=5,
                )
                self.assertEqual(42, second.returncode, second.stderr)
                self.assertIn("already running", second.stderr)
            finally:
                if first.stdin:
                    first.stdin.write("\n")
                    first.stdin.flush()
                    first.stdin.close()
                first.wait(timeout=5)
                if first.stdout:
                    first.stdout.close()
                if first.stderr:
                    first.stderr.close()


class SigningKeyBehaviorTests(unittest.TestCase):
    FINGERPRINT = "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"

    def verify_listing(self, listing: str, exit_code: int = 0) -> subprocess.CompletedProcess[str]:
        definition = bash_function("verify_primary_key_fingerprint")
        with tempfile.TemporaryDirectory() as temporary_directory:
            command_directory = Path(temporary_directory)
            fake_gpg = command_directory / "gpg"
            listing_path = command_directory / "listing"
            listing_path.write_text(listing, encoding="utf-8")
            fake_gpg.write_text(
                "#!/bin/sh\n"
                "homedir=\n"
                "while [ \"$#\" -gt 0 ]; do\n"
                "  if [ \"$1\" = --homedir ]; then\n"
                "    shift\n"
                "    homedir=$1\n"
                "  fi\n"
                "  shift\n"
                "done\n"
                "case $homedir in\n"
                "  \"$VIBESTACK_TEST_GPG_PARENT\"/gnupg.*) ;;\n"
                "  *) exit 91 ;;\n"
                "esac\n"
                "[ -d \"$homedir\" ] || exit 92\n"
                "[ \"$(/usr/bin/stat -c %a -- \"$homedir\")\" = 700 ] || exit 93\n"
                "[ ! -e \"$HOME/.gnupg\" ] || exit 94\n"
                f"/bin/cat -- {shlex.quote(str(listing_path))}\n"
                f"exit {exit_code}\n",
                encoding="utf-8",
            )
            fake_gpg.chmod(0o755)
            install_tmp = command_directory / "install-tmp"
            install_tmp.mkdir(mode=0o700)
            missing_home = command_directory / "missing-home"
            script = f"""
set -uo pipefail
INSTALL_TMPDIR=$2
say() {{ printf '%s\\n' "$*" >&2; }}
{definition}
verify_primary_key_fingerprint /unused "$1"
"""
            return subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    script,
                    "key-test",
                    self.FINGERPRINT,
                    str(install_tmp),
                ],
                env={
                    "HOME": str(missing_home),
                    "PATH": f"{command_directory}:/usr/bin:/bin",
                    "VIBESTACK_TEST_GPG_PARENT": str(install_tmp),
                },
                text=True,
                capture_output=True,
                check=False,
            )

    def test_exact_single_primary_fingerprint_is_accepted(self) -> None:
        listing = (
            "pub:-:255:22:ABC:0:0:::::::\n"
            f"fpr:::::::::{self.FINGERPRINT}:\n"
            "sub:-:255:18:DEF:0:0:::::::\n"
            "fpr:::::::::AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:\n"
        )
        result = self.verify_listing(listing)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_subkey_match_extra_primary_and_gpg_failure_are_rejected(self) -> None:
        cases = {
            "subkey only": (
                "pub:-:255:22:ABC:0:0:::::::\n"
                "fpr:::::::::BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB:\n"
                "sub:-:255:18:DEF:0:0:::::::\n"
                f"fpr:::::::::{self.FINGERPRINT}:\n",
                0,
            ),
            "extra primary": (
                "pub:-:255:22:ABC:0:0:::::::\n"
                f"fpr:::::::::{self.FINGERPRINT}:\n"
                "pub:-:255:22:DEF:0:0:::::::\n"
                "fpr:::::::::CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC:\n",
                0,
            ),
            "gpg failure": ("", 2),
        }
        for label, (listing, exit_code) in cases.items():
            with self.subTest(label=label):
                result = self.verify_listing(listing, exit_code)
                self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
