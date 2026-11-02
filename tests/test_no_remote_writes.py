"""Safety gate: this HACS feature branch must not write to OMOTE firmware."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"


class TestNoRemoteMutations(unittest.TestCase):
    def test_api_transport_has_only_get_requests(self):
        tree = ast.parse((ROOT / "api.py").read_text())
        session_methods = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"post", "put", "patch", "delete", "request"}:
                    session_methods.append(node.func.attr)
        self.assertEqual(session_methods, [])

    def test_capabilities_never_enable_deployment(self):
        source = (ROOT / "capability_model.py").read_text()
        self.assertNotIn('"deployment_enabled": True', source)
        self.assertIn('"deployment_enabled": False', source)
        self.assertIn('"deployment_enabled"] = False', (ROOT / "panel.py").read_text())

    def test_review_and_recovery_do_not_write_remote(self):
        for name in ("release_ws.py", "editor_ws.py", "workspace_ws.py"):
            source = (ROOT / name).read_text()
            self.assertNotIn("._session.post(", source)
            self.assertNotIn("._session.put(", source)
            self.assertNotIn("/api/config/v2/transactions/", source)
        js = (ROOT / "frontend/scene-editor.js").read_text()
        self.assertIn('id="se-recovery-check"', js)
        self.assertIn('id="se-save-reviewed"', js)
        self.assertIn('type="button" disabled title="Requires HA admin', js)
        self.assertIn("No automatic", js)


if __name__ == "__main__":
    unittest.main()
