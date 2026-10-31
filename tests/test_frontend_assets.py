"""Prevent invisible sidebar regressions caused by stale custom elements.

Static contract tests cover integration version, frontend element registration,
the Profile Studio navigation button, and all imported static assets.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
FRONTEND = ROOT / "frontend"


class TestFrontendVersionContract(unittest.TestCase):
    def test_versioned_custom_element_matches_python_registration(self):
        panel_py = (ROOT / "panel.py").read_text()
        panel_js = (FRONTEND / "omote-panel.js").read_text()
        manifest = json.loads((ROOT / "manifest.json").read_text())
        version = manifest["version"]
        tag_match = re.search(r'PANEL_ELEMENT = "([^"]+)"', panel_py)
        asset_match = re.search(r'ASSET_VERSION = "([^"]+)"', panel_py)
        self.assertIsNotNone(tag_match)
        self.assertIsNotNone(asset_match)
        tag = tag_match.group(1)
        self.assertEqual(asset_match.group(1), version)
        self.assertRegex(tag, r"^omote-manager-panel-v\d+$")
        self.assertIn(f'customElements.define("{tag}"', panel_js)
        self.assertIn(f'customElements.get("{tag}"', panel_js)

    def test_navigation_load_placeholder_and_editor_asset(self):
        panel_js = (FRONTEND / "omote-panel.js").read_text()
        manifest = json.loads((ROOT / "manifest.json").read_text())
        version = manifest["version"]
        self.assertIn('id="nav-studio"', panel_js)
        self.assertIn('id="studio-load-state"', panel_js)
        self.assertIn("Profile Studio failed to initialize", panel_js)
        self.assertIn("_loadStudio()", panel_js)
        self.assertIn(f'workspace-panel.js?v={version}', panel_js)
        self.assertTrue((FRONTEND / "workspace-panel.js").is_file())
        self.assertTrue((FRONTEND / "workspace.css").is_file())
        self.assertIn("attachWorkspace", (FRONTEND / "workspace-panel.js").read_text())


if __name__ == "__main__":
    unittest.main()
