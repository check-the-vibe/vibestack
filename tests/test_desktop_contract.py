"""Source-level contract checks for the dependency-free desktop shell."""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import struct
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1] / "desktop"
PROJECT_ROOT = ROOT.parent


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.attributes_by_id: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        for name, value in attrs:
            if name == "id" and value:
                self.ids.append(value)
                self.attributes_by_id[value] = attributes


class DesktopShellContractTests(unittest.TestCase):
    def test_launcher_defaults_to_loopback_publish(self) -> None:
        source = (PROJECT_ROOT / "startup.sh").read_text(encoding="utf-8")
        self.assertIn('VIBESTACK_BIND_ADDRESS:-127.0.0.1', source)
        self.assertIn('-p "${BIND_ADDRESS}:${PORT}:80"', source)

    def test_html_has_unique_ids_and_primary_surfaces(self) -> None:
        parser = IdCollector()
        parser.feed((ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertTrue(
            {
                "screen",
                "desktop-view-tab",
                "terminal-view-tab",
                "terminal-stage",
                "terminal-frame",
                "connection-panel",
                "settings-dialog",
                "tools-dialog",
                "clipboard-dialog",
                "virtual-keyboard",
                "render-profile",
            }.issubset(parser.ids)
        )

    def test_root_lands_on_desktop_and_only_forwards_supported_navigation(self) -> None:
        script = (ROOT / "launcher.js").read_text(encoding="utf-8")
        self.assertIn("new URL('/vnc/', source)", script)
        self.assertIn("panel:['apps','settings']", script)
        self.assertIn("window.location.replace", script)
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        for name in ("desktop-stage", "terminal-stage", "editor-stage", "apps-dialog", "settings-dialog"):
            self.assertIn('id="' + name + '"', html)

    def test_workspace_view_tabs_and_terminal_frame_are_accessible(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        parser = IdCollector()
        parser.feed(html)
        desktop_tab = parser.attributes_by_id["desktop-view-tab"]
        terminal_tab = parser.attributes_by_id["terminal-view-tab"]
        terminal_frame = parser.attributes_by_id["terminal-frame"]
        self.assertEqual("tab", desktop_tab.get("role"))
        self.assertEqual("desktop-stage", desktop_tab.get("aria-controls"))
        self.assertEqual("tab", terminal_tab.get("role"))
        self.assertEqual("terminal-stage", terminal_tab.get("aria-controls"))
        self.assertEqual("/terminal/", terminal_frame.get("data-src"))
        self.assertEqual("VibeStack browser terminal", terminal_frame.get("title"))

    def test_all_desktop_controls_share_one_collapsed_topbar_menu(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        parser = IdCollector()
        parser.feed(html)
        self.assertNotIn("touch-dock", html)
        self.assertTrue(
            {
                "input-controls-button",
                "input-controls-panel",
                "match-screen-button",
                "auto-resize-toggle",
                "settings-button",
                "tools-button",
            }.issubset(parser.ids)
        )
        trigger = parser.attributes_by_id["input-controls-button"]
        self.assertEqual("input-controls-panel", trigger.get("aria-controls"))
        self.assertEqual("false", trigger.get("aria-expanded"))
        self.assertEqual("input-controls-toggle", trigger.get("data-testid"))
        panel = parser.attributes_by_id["input-controls-panel"]
        self.assertIn("hidden", panel)
        self.assertEqual("input-controls-panel", panel.get("data-testid"))
        panel_markup = html[
            html.index('id="input-controls-panel"') : html.index("</header>")
        ]
        self.assertIn('id="settings-button"', panel_markup)
        self.assertIn('id="tools-button"', panel_markup)
        auto_resize = parser.attributes_by_id["auto-resize-toggle"]
        self.assertEqual("checkbox", auto_resize.get("type"))
        self.assertEqual("switch", auto_resize.get("role"))

    def test_manifest_uses_root_scope_and_raster_install_icons(self) -> None:
        manifest = json.loads((ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertIn("maskable", {icon["purpose"] for icon in manifest["icons"]})
        sizes = {icon["sizes"] for icon in manifest["icons"] if icon["type"] == "image/png"}
        self.assertTrue({"192x192", "512x512"}.issubset(sizes))

    def test_client_uses_public_rfb_and_exact_control_contract(self) -> None:
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("from '/novnc/core/rfb.js'", source)
        self.assertIn("new URL('/vnc/websockify'", source)
        for endpoint in ("/status", "/display", "/services/", "/logs/"):
            self.assertIn(endpoint, source)
        for field in ("uptimeSeconds", "availableBytes", "availableResolutions"):
            self.assertIn(field, source)
        self.assertIn("serververification", source)
        self.assertIn("RETRY_DELAYS", source)
        self.assertIn("RENDER_PROFILES", source)
        self.assertNotIn("localStorage.setItem('clipboard", source)
        self.assertIn("navigator.clipboard?.writeText", source)
        self.assertIn("elements.clipboardText.select()", source)
        self.assertIn("workspaceViewFromLocation", source)
        self.assertIn("window.history.pushState", source)

    def test_expected_vnc_restart_recovers_even_after_a_clean_disconnect(self) -> None:
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("expectingVncRestart: false", source)
        self.assertIn("recoveringVncRestart: false", source)
        self.assertIn("scheduleReconnect('VNC is restarting.', { force: true })", source)
        self.assertIn("{ force: state.recoveringVncRestart }", source)

    def test_initial_connection_failure_requires_manual_retry(self) -> None:
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("hasConnected: false", source)
        self.assertIn("state.hasConnected = true", source)
        failure_handler = source[
            source.index("function handleConnectionFailure") : source.index(
                "function stopConnection"
            )
        ]
        self.assertIn("if (!state.hasConnected)", failure_handler)
        self.assertIn("stopConnection(", failure_handler)
        self.assertIn("scheduleReconnect(", failure_handler)
        disconnect_handler = source[
            source.index("rfb.addEventListener('disconnect'") : source.index(
                "rfb.addEventListener('securityfailure'"
            )
        ]
        self.assertIn("handleConnectionFailure(", disconnect_handler)
        self.assertEqual(disconnect_handler.count("scheduleReconnect("), 2)
        self.assertIn("state.expectingVncRestart", disconnect_handler)
        self.assertIn("state.expectingDisplayResize", disconnect_handler)
        self.assertIn("The desktop display is resizing.", disconnect_handler)
        manual_handler = source[
            source.index("function manualConnect") : source.index(
                "function scheduleReconnect"
            )
        ]
        self.assertIn("state.hasConnected = false", manual_handler)

    def test_virtual_keyboard_has_mobile_edit_and_composition_buffer(self) -> None:
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("const VIRTUAL_KEYBOARD_SENTINEL", source)
        self.assertIn("virtualKeyboardValue: VIRTUAL_KEYBOARD_SENTINEL", source)
        self.assertIn("function virtualKeyboardDelta", source)
        self.assertIn("for (let index = 0; index < backspaces", source)
        self.assertIn("sendKey(SPECIAL_KEYS.Backspace)", source)
        self.assertIn("sendText(inserted)", source)
        self.assertIn("event.isComposing || state.keyboardComposing", source)
        self.assertIn("addEventListener('compositionstart'", source)
        self.assertIn("addEventListener('compositionend'", source)
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('autocorrect="off"', html)

    def test_dialogs_explicitly_close_on_escape_and_restore_focus(self) -> None:
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("const dialogInvokers = new WeakMap()", source)
        self.assertIn("event.key !== 'Escape'", source)
        self.assertIn("dialogInvokers.get(dialog)", source)

    def test_service_worker_excludes_live_routes_and_precaches_module_graph(self) -> None:
        source = (ROOT / "service-worker.js").read_text(encoding="utf-8")
        for route in ("'/api/'", "'/terminal/'", "'/setup/'", "'/vnc/websockify'"):
            self.assertIn(route, source)
        self.assertIn("request.method !== 'GET'", source)
        self.assertIn("url.origin !== self.location.origin", source)
        self.assertIn("/novnc/core/decoders/tight.js", source)
        self.assertIn("/novnc/vendor/pako/lib/zlib/inflate.js", source)
        self.assertIn("'/launcher.css'", source)
        self.assertIn("url.pathname === '/'", source)
        install_block = source[source.index("self.addEventListener('install'"):source.index("self.addEventListener('activate'")]
        self.assertNotIn("skipWaiting", install_block)
        self.assertIn("__VIBESTACK_SHELL_CACHE_VERSION__", source)
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("shell_cache_version", dockerfile)
        self.assertIn("/usr/share/novnc/core /usr/share/novnc/vendor", dockerfile)

    def test_vector_sources_and_raster_icon_dimensions(self) -> None:
        for name in ("icon.svg", "icon-maskable.svg"):
            root = ET.parse(ROOT / "icons" / name).getroot()
            self.assertTrue(root.tag.endswith("svg"))
            self.assertEqual(root.attrib.get("viewBox"), "0 0 512 512")

        expected = {
            "icon-180.png": (180, 180),
            "icon-192.png": (192, 192),
            "icon-512.png": (512, 512),
            "icon-maskable-512.png": (512, 512),
        }
        for name, dimensions in expected.items():
            data = (ROOT / "icons" / name).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), dimensions)


if __name__ == "__main__":
    unittest.main()
