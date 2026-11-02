"""Safety regression: HACS preview has no firmware mutation transport.

The secure Config v2 firmware transaction protocol has not been implemented.
No change to a manifest/capability advertisement can authorize HTTP writes.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"


class TestNoRemoteWrites(unittest.TestCase):
    def test_api_has_no_http_mutation_methods(self):
        source = (ROOT / "api.py").read_text()
        tree = ast.parse(source)
        methods = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"post", "put", "patch", "delete", "request"}:
                    methods.append(node.func.attr)
        self.assertEqual(methods, [])

    def test_reviewed_storage_cannot_call_remote_transport(self):
        for filename in (
            "reviewed_ws.py", "workspace_store.py", "workspace_ws.py",
            "release_model.py", "single_active_manifest.py",
        ):
            source = (ROOT / filename).read_text()
            self.assertNotIn("._session.post(", source)
            self.assertNotIn("._session.put(", source)
            self.assertNotIn("._session.delete(", source)
            self.assertNotIn("/api/config/v2/transactions", source)

    def test_deployment_controls_and_capabilities_remain_disabled(self):
        self.assertNotIn(
            '"deployment_enabled": True',
            (ROOT / "capability_model.py").read_text()
        )
        self.assertIn(
            'info["deployment_enabled"] = False',
            (ROOT / "panel.py").read_text()
        )
        scene = (ROOT / "frontend/scene-editor.js").read_text()
        workspace = (ROOT / "frontend/workspace-panel.js").read_text()
        self.assertIn('id="se-recovery-resend" disabled', scene)
        self.assertIn('id="se-retain-reviewed" disabled', scene)
        self.assertIn('id="studio-deploy" type="button" disabled', workspace)
        self.assertIn("No automatic", (ROOT / "frontend/omote-panel.js").read_text())


if __name__ == "__main__":
    unittest.main()
