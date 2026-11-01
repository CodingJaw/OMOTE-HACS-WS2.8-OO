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
        scene_module = FRONTEND / "scene-editor.js"
        self.assertTrue(scene_module.is_file())
        self.assertIn("attachSceneEditor", scene_module.read_text())
        self.assertIn("scene-editor.js?v=", (FRONTEND / "workspace-panel.js").read_text())
        self.assertIn("register_editor_websockets", (ROOT / "workspace_ws.py").read_text())
        visual = FRONTEND / "layout-editor.js"
        self.assertTrue(visual.is_file())
        self.assertIn("attachVisualLayoutEditor", visual.read_text())
        self.assertIn("layout-editor.js?v=", scene_module.read_text())
        self.assertTrue((FRONTEND / "layout-editor.css").is_file())
        self.assertIn("omote_manager/editor/edit-layout", (ROOT / "editor_ws.py").read_text())
        self.assertIn("layout_description", (ROOT / "editor_model.py").read_text())
        # Colored changes must not be rendered as untrusted HTML.
        diff_view = scene_module.read_text()
        for class_name in (
            "se-diff-add", "se-diff-remove", "se-diff-hunk",
            "se-diff-context", "se-diff-file-header",
        ):
            self.assertIn(class_name, diff_view)
            self.assertIn(class_name, (FRONTEND / "scene-editor.css").read_text())
        self.assertIn("node.textContent = line", diff_view)
        self.assertIn("se-only-changes", diff_view)
        self.assertIn("omote_manager/editor/preflight", diff_view)
        self.assertIn("ws_preflight", (ROOT / "editor_ws.py").read_text())
        self.assertIn("apply_live_results", (ROOT / "review_model.py").read_text())
        self.assertIn("se-kit-download", diff_view)
        self.assertIn("omote_manager/editor/export-kit", diff_view)
        self.assertIn("atob(result.base64)", diff_view)
        self.assertIn("register_release_websockets", (ROOT / "editor_ws.py").read_text())
        self.assertIn("omote_manager/editor/export-kit", (ROOT / "release_ws.py").read_text())
        self.assertIn("build_deployment_kit", (ROOT / "release_model.py").read_text())
        self.assertIn("proposed", (ROOT / "release_model.py").read_text())
        self.assertIn("rollback", (ROOT / "release_model.py").read_text())
        backup_history = (ROOT / "backup_history.py").read_text()
        backup_ws = (ROOT / "backup_ws.py").read_text()
        workspace_js = (FRONTEND / "workspace-panel.js").read_text()
        self.assertIn("OmoteBackupHistory", (ROOT / "__init__.py").read_text())
        self.assertIn("register_backup_websockets", (ROOT / "workspace_ws.py").read_text())
        self.assertIn("omote_manager/backups/list", backup_ws)
        self.assertIn("omote_manager/backups/load-to-draft", backup_ws)
        self.assertIn("snapshot[\"sha256\"]", backup_history)
        self.assertIn("studio-backup-select", workspace_js)
        self.assertIn("loadBackupDraft()", workspace_js)
        self.assertIn("does NOT restore", workspace_js)
        capability_panel = (ROOT / "panel.py").read_text()
        capability_api = (ROOT / "api.py").read_text()
        self.assertIn("omote_manager/capabilities", capability_panel)
        self.assertIn("async def capabilities", capability_api)
        self.assertIn("allow_redirects=False", capability_api)
        self.assertIn("inspect-capabilities", panel_js)
        self.assertIn("deployment_enabled", (ROOT / "capability_model.py").read_text())
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertIn("_omote._tcp.local.", manifest["zeroconf"])
        self.assertIn("zeroconf", manifest["dependencies"])
        flow = (ROOT / "config_flow.py").read_text()
        self.assertIn("async_step_zeroconf", flow)
        self.assertIn("async_step_zeroconf_confirm", flow)
        self.assertIn("self._matching_entry", flow)
        self.assertIn("self.async_show_form", flow)
        self.assertIn("storage_status", panel_js)
        self.assertIn("async def storage_status", capability_api)
        self.assertIn("summarize_storage_status", (ROOT / "capability_model.py").read_text())








if __name__ == "__main__":
    unittest.main()
