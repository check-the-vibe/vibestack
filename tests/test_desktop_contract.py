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

    def test_html_has_unique_ids_and_accessible_overlay(self) -> None:
        parser = IdCollector()
        parser.feed((ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertTrue({"screen", "agent-toggle", "agent-panel", "credential-form",
                         "password-form", "provider-select", "message-form", "approvals"}.issubset(parser.ids))
        trigger = parser.attributes_by_id["agent-toggle"]
        self.assertEqual(trigger.get("aria-controls"), "agent-panel")
        self.assertEqual(trigger.get("aria-expanded"), "false")
        panel = parser.attributes_by_id["agent-panel"]
        self.assertEqual(panel.get("role"), "dialog")
        self.assertEqual(panel.get("aria-modal"), "false")
        self.assertIn("hidden", panel)
        for old in ("terminal-stage", "editor-stage", "settings-dialog", "apps-dialog", "input-controls-panel"):
            self.assertNotIn(old, parser.ids)

    def test_old_root_navigation_does_not_restore_retired_panels(self) -> None:
        script = (ROOT / "launcher.js").read_text(encoding="utf-8")
        self.assertIn("new URL('/vnc/', source)", script)
        self.assertNotIn("panel:", script)
        self.assertNotIn("view:", script)

    def test_manifest_uses_root_scope_and_raster_install_icons(self) -> None:
        manifest = json.loads((ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertIn("maskable", {icon["purpose"] for icon in manifest["icons"]})
        sizes = {icon["sizes"] for icon in manifest["icons"] if icon["type"] == "image/png"}
        self.assertTrue({"192x192", "512x512"}.issubset(sizes))

    def test_client_preserves_public_rfb_and_secret_boundaries(self) -> None:
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("from '/novnc/core/rfb.js'", source)
        self.assertIn("new URL('/vnc/websockify'", source)
        self.assertIn("resizeSession=false", source)
        self.assertIn("serververification", source)
        self.assertIn("RETRY_DELAYS", source)
        self.assertNotIn("innerHTML", source)
        self.assertNotIn("localStorage", source)
        self.assertNotIn("sessionStorage", source)
        self.assertNotIn("console.", source)
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('src="/terminal/', html)
        self.assertNotIn('src="/editor/', html)

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
