"""Release identity must agree across executable, installer and served metadata."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_metadata_and_bootstrap_guide_agree(self):
        manifest = json.loads((ROOT / "release-manifest.json").read_text())
        version = manifest["version"]
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertEqual(version, manifest["workspace"]["version"])
        self.assertEqual(version, manifest["runner"]["version"])
        source_version = re.search(r'Version\s*=\s*"([^"]+)"', (ROOT / "internal/release/version.go").read_text()).group(1)
        self.assertEqual(version, source_version)
        self.assertIn(f'version="{version}"', (ROOT / "cli.sh").read_text())
        self.assertIn(f"**{version}**", (ROOT / "runtime/AGENTS.md").read_text())
        self.assertTrue((ROOT / f"docs/releases/{version}.md").is_file())
        self.assertIn("COPY release-manifest.json /usr/share/vibestack/public/release-manifest.json", (ROOT / "Dockerfile").read_text())
