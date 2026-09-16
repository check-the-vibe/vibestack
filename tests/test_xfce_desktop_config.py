"""Contracts for VibeStack's native XFCE panel, menu, and safe actions."""

from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "desktop-config"
APPLICATIONS = CONFIG / "usr/share/applications"
DIRECTORIES = CONFIG / "usr/share/desktop-directories"
PANEL = CONFIG / "etc/xdg/xfce4/panel/default.xml"
MENU = CONFIG / "etc/xdg/menus/vibestack-applications.menu"
MIMEAPPS = CONFIG / "etc/xdg/mimeapps.list"
ACTION = ROOT / "bin/vibestack-desktop-action"
XFCE_STARTUP = ROOT / "xfce-startup"


def properties(element: ET.Element) -> dict[str, ET.Element]:
    return {
        child.attrib["name"]: child
        for child in element.findall("property")
    }


def desktop_entry(path: Path) -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    with path.open(encoding="utf-8") as stream:
        parser.read_file(stream)
    return parser["Desktop Entry"]


class XfceDesktopConfigTests(unittest.TestCase):
    def test_panel_is_one_clean_native_panel(self) -> None:
        root = ET.parse(PANEL).getroot()
        channel = properties(root)
        panels = channel["panels"]
        panel_ids = [value.attrib["value"] for value in panels.findall("value")]
        self.assertEqual(["1"], panel_ids)

        panel = properties(panels)["panel-1"]
        panel_config = properties(panel)
        self.assertEqual("100", panel_config["length"].attrib["value"])
        self.assertEqual("true", panel_config["position-locked"].attrib["value"])
        self.assertEqual("32", panel_config["size"].attrib["value"])

        plugins = properties(channel["plugins"])
        plugin_types = [plugin.attrib.get("value") for plugin in plugins.values()]
        self.assertEqual(
            [
                "applicationsmenu",
                "launcher",
                "launcher",
                "tasklist",
                "separator",
                "systray",
                "clock",
                "showdesktop",
            ],
            plugin_types,
        )
        self.assertNotIn("pager", plugin_types)
        self.assertNotIn("actions", plugin_types)
        self.assertNotIn("windowmenu", plugin_types)

        menu_plugin = properties(plugins["plugin-1"])
        self.assertEqual("VibeStack", menu_plugin["button-title"].attrib["value"])
        self.assertEqual("true", menu_plugin["show-button-title"].attrib["value"])
        self.assertEqual("true", menu_plugin["custom-menu"].attrib["value"])
        self.assertNotIn("use-custom-menu", menu_plugin)
        self.assertEqual(
            "/etc/xdg/menus/vibestack-applications.menu",
            menu_plugin["custom-menu-file"].attrib["value"],
        )

        configured_ids = [
            value.attrib["value"]
            for value in properties(panel)["plugin-ids"].findall("value")
        ]
        self.assertEqual(
            [name.removeprefix("plugin-") for name in plugins],
            configured_ids,
        )

    def test_custom_menu_has_only_vibestack_use_case_collections(self) -> None:
        root = ET.parse(MENU).getroot()
        menus = {menu.findtext("Name"): menu for menu in root.findall("Menu")}
        self.assertEqual(
            {
                "VibeStack",
                "Coding",
                "CreateAndReview",
                "Applications",
                "SystemAndSettings",
            },
            set(menus),
        )
        root_order = [item.text for item in root.find("Layout").findall("Menuname")]
        self.assertEqual(
            [
                "VibeStack",
                "Coding",
                "CreateAndReview",
                "Applications",
                "SystemAndSettings",
            ],
            root_order,
        )

        action_filenames = {
            item.text for item in menus["VibeStack"].find("Layout").findall("Filename")
        }
        self.assertEqual(
            {
                "vibestack-workspace-desktop.desktop",
                "vibestack-terminal.desktop",
                "vibestack-editor.desktop",
                "vibestack-settings.desktop",
                "vibestack-projects.desktop",
                "vibestack-desktop.desktop",
                "vibestack-logs.desktop",
                "vibestack-setup.desktop",
                "vibestack-agent-guide.desktop",
                "vibestack-automation-guide.desktop",
                "vibestack-service-status.desktop",
                "vibestack-flathub.desktop",
                "vibestack-flatpak.desktop",
                "vibestack-screenshot.desktop",
            },
            action_filenames,
        )
        for filename in action_filenames:
            self.assertTrue((APPLICATIONS / filename).is_file(), filename)

        forbidden_root_items = {
            "xfce4-run.desktop",
            "xfce4-session-logout.desktop",
            "xfce4-logout.desktop",
            "xfce4-about.desktop",
            "xfce4-about-xfce.desktop",
            "xfce4-mail-reader.desktop",
            "xfce4-web-browser.desktop",
        }
        visible_layout_files = {
            item.text
            for layout in root.findall(".//Layout")
            for item in layout.findall("Filename")
        }
        self.assertTrue(forbidden_root_items.isdisjoint(visible_layout_files))

    def test_optional_apps_are_discovered_by_standard_categories_and_tryexec(self) -> None:
        root = ET.parse(MENU).getroot()
        menus = {menu.findtext("Name"): menu for menu in root.findall("Menu")}
        categories = {
            name: {node.text for node in menu.findall("./Include//Category")}
            for name, menu in menus.items()
        }
        self.assertIn("Development", categories["Coding"])
        self.assertTrue(
            {"Graphics", "Office", "AudioVideo"}.issubset(categories["CreateAndReview"])
        )
        self.assertTrue({"Settings", "System"}.issubset(categories["SystemAndSettings"]))
        self.assertTrue(
            {"Network", "Utility", "Game", "Education", "Science"}.issubset(
                categories["Applications"]
            )
        )
        coding_files = {
            node.text for node in menus["Coding"].findall("./Include//Filename")
        }
        self.assertIn("google-chrome.desktop", coding_files)

        expected = {
            "vibestack-claude-code.desktop": "claude",
            "vibestack-codex.desktop": "codex",
            "vibestack-opencode.desktop": "opencode",
        }
        for filename, binary in expected.items():
            entry = desktop_entry(APPLICATIONS / filename)
            self.assertEqual(binary, entry["TryExec"])
            self.assertIn("Development", entry["Categories"].split(";"))

    def test_desktop_files_use_only_the_fixed_action_dispatcher(self) -> None:
        entries = sorted(APPLICATIONS.glob("vibestack-*.desktop"))
        self.assertGreaterEqual(len(entries), 13)
        for path in entries:
            entry = desktop_entry(path)
            self.assertEqual("Application", entry["Type"])
            self.assertEqual("false", entry["Terminal"])
            self.assertTrue(
                entry["Exec"].startswith("/usr/local/bin/vibestack-desktop-action "),
                path.name,
            )
            self.assertEqual("XFCE;", entry["OnlyShowIn"])

        validator = shutil.which("desktop-file-validate")
        if validator:
            result = subprocess.run(
                [
                    validator,
                    *map(str, entries),
                    *map(str, sorted(DIRECTORIES.glob("*.directory"))),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)

    def test_flathub_install_actions_have_hidden_review_handlers(self) -> None:
        handler_id = "vibestack-flatpakref.desktop"
        mime_type = "application/vnd.flatpak.ref"
        entry = desktop_entry(APPLICATIONS / handler_id)
        self.assertEqual(
            "/usr/local/bin/vibestack-desktop-action flatpak-ref %f",
            entry["Exec"],
        )
        self.assertEqual("/usr/bin/flatpak", entry["TryExec"])
        self.assertEqual("true", entry["NoDisplay"])
        self.assertIn(mime_type, entry["MimeType"].split(";"))

        defaults = configparser.ConfigParser(interpolation=None, strict=True)
        defaults.optionxform = str
        with MIMEAPPS.open(encoding="utf-8") as stream:
            defaults.read_file(stream)
        self.assertEqual(
            f"{handler_id};",
            defaults["Default Applications"][mime_type],
        )
        self.assertEqual(
            f"{handler_id};",
            defaults["Added Associations"][mime_type],
        )

        url_handler_id = "vibestack-flatpak-url.desktop"
        url_mime_type = "x-scheme-handler/flatpak+https"
        url_entry = desktop_entry(APPLICATIONS / url_handler_id)
        self.assertEqual(
            "/usr/local/bin/vibestack-desktop-action flatpak-url %u",
            url_entry["Exec"],
        )
        self.assertEqual("/usr/bin/flatpak", url_entry["TryExec"])
        self.assertEqual("true", url_entry["NoDisplay"])
        self.assertIn(url_mime_type, url_entry["MimeType"].split(";"))
        self.assertEqual(
            f"{url_handler_id};",
            defaults["Default Applications"][url_mime_type],
        )
        self.assertEqual(
            f"{url_handler_id};",
            defaults["Added Associations"][url_mime_type],
        )
        self.assertNotIn("application/vnd.flatpak.repo", MIMEAPPS.read_text())

        action = ACTION.read_text(encoding="utf-8")
        self.assertIn("desktop-mime", action)
        self.assertIn('vibestack-flatpak install-ref "$1"', action)
        self.assertIn('vibestack-flatpak install-url "$1"', action)

    def test_action_dispatcher_uses_runtime_and_persistent_contracts(self) -> None:
        source = ACTION.read_text(encoding="utf-8")
        self.assertIn("/run/vibestack/session.env", source)
        self.assertIn("/run/vibestack/Xauthority", source)
        self.assertIn("/data/logs/vibestack", source)
        self.assertIn("desktop/actions.jsonl", source)
        self.assertIn("ACTION_LOG_MAX_BYTES=1048576", source)
        self.assertIn("flock --exclusive --wait 2", source)
        self.assertIn('mv -f "$log_file.1" "$log_file.2"', source)
        self.assertIn("/usr/share/doc/vibestack/AUTOMATION.md", source)
        self.assertIn("/usr/share/doc/vibestack/AGENTS.md", source)
        self.assertIn("https://flathub.org", source)
        self.assertIn("/usr/local/bin/vibestack-flatpak", source)
        self.assertIn("http://127.0.0.1/setup/?force=1", source)
        self.assertIn("http://127.0.0.1/api/v1/status", source)
        self.assertNotIn("http://127.0.0.1/api/v1/automation", source)
        self.assertIn('export DISPLAY="${DISPLAY:-:0}"', source)
        self.assertNotIn("eval ", source)
        self.assertNotIn("sudo ", source)
        self.assertNotRegex(source, r"\brm\b")
        self.assertNotRegex(source, r"\bkill(?:all)?\b")

    def test_xfce_publishes_one_private_runtime_session_contract(self) -> None:
        source = XFCE_STARTUP.read_text(encoding="utf-8")
        self.assertIn("/run/vibestack/runtime", source)
        self.assertIn("/run/vibestack/Xauthority", source)
        self.assertIn("SESSION_ENV_FILE=/run/vibestack/session.env", source)
        self.assertIn('chmod 600 "$session_env_tmp"', source)
        self.assertIn('mv -f "$session_env_tmp" "$SESSION_ENV_FILE"', source)
        for variable in (
            "DISPLAY",
            "XAUTHORITY",
            "XDG_RUNTIME_DIR",
            "XDG_CURRENT_DESKTOP",
            "XDG_SESSION_TYPE",
            "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME",
            "XDG_DATA_HOME",
            "XDG_DATA_DIRS",
            "DBUS_SESSION_BUS_ADDRESS",
            "GNOME_KEYRING_CONTROL",
        ):
            self.assertRegex(source, rf"printf 'export {variable}=%q")
        self.assertNotIn("/tmp/runtime-vibe", source)
        self.assertNotIn("> /tmp/vibestack-session.env", source)
        self.assertIn("/general/use_compositing", source)
        self.assertIn("--compositor=off", source)

    def test_screenshot_is_timestamped_and_action_log_is_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            fake_bin = root / "bin"
            screenshots = root / "screenshots"
            logs = root / "logs"
            home.mkdir()
            fake_bin.mkdir()
            logs.mkdir()
            capture = root / "scrot.json"
            action_log = logs / "desktop/actions.jsonl"
            action_log.parent.mkdir()
            action_log.write_bytes(b"x" * 1_048_576)
            action_log.with_suffix(".jsonl.1").write_text("older\n", encoding="utf-8")

            fake_scrot = fake_bin / "scrot"
            fake_scrot.write_text(
                "#!/bin/sh\n"
                "python3 -c 'import json,os,sys; "
                "open(os.environ[\"TEST_CAPTURE\"], \"w\").write(json.dumps({\"display\": os.environ.get(\"DISPLAY\"), \"path\": sys.argv[1]}))' \"$1\"\n"
                ": > \"$1\"\n",
                encoding="utf-8",
            )
            fake_scrot.chmod(0o755)
            fake_notify = fake_bin / "notify-send"
            fake_notify.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_notify.chmod(0o755)

            environment = os.environ.copy()
            environment.update(
                HOME=str(home),
                DISPLAY=":77",
                PATH=f"{fake_bin}:/usr/bin:/bin",
                TEST_CAPTURE=str(capture),
                VIBESTACK_LOGS_DIR=str(logs),
                VIBESTACK_SCREENSHOT_DIR=str(screenshots),
            )
            result = subprocess.run(
                [str(ACTION), "screenshot"],
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)

            invocation = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(":77", invocation["display"])
            screenshot = Path(invocation["path"])
            self.assertTrue(screenshot.is_file())
            self.assertEqual(screenshots, screenshot.parent)
            self.assertRegex(
                screenshot.name,
                r"^VibeStack-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d+\.png$",
            )

            records = action_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, len(records))
            record = json.loads(records[0])
            self.assertEqual(
                {"timestamp", "source", "action", "outcome"}, set(record)
            )
            self.assertEqual("xfce-menu", record["source"])
            self.assertEqual("screenshot", record["action"])
            self.assertEqual("launched", record["outcome"])
            self.assertRegex(record["timestamp"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertNotIn(str(screenshot), records[0])
            self.assertEqual(1_048_576, action_log.with_suffix(".jsonl.1").stat().st_size)
            self.assertEqual(
                "older\n",
                action_log.with_suffix(".jsonl.2").read_text(encoding="utf-8"),
            )

    def test_coding_dispatch_rejects_commands_outside_allowlist(self) -> None:
        result = subprocess.run(
            [str(ACTION), "coding", "bash"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
