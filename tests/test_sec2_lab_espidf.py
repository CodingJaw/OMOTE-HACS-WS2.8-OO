"""Offline fail-closed checks for the opt-in official Espressif client loader."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/omote_manager"
spec = importlib.util.spec_from_file_location(
    "omote_lab_espidf_loader_tests", COMPONENT / "sec2_lab_espidf.py"
)
loader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = loader
spec.loader.exec_module(loader)


class EspIdfLabLoaderTests(unittest.TestCase):
    def test_disabled_missing_idf_path_fails_before_import(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(
            loader.LabPrerequisiteError
        ) as context:
            loader.load_official_security2()
        self.assertEqual(str(context.exception), "idf_path_not_configured")

    def test_unknown_source_tree_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"IDF_PATH": folder}, clear=True):
                with self.assertRaises(loader.LabPrerequisiteError) as context:
                    loader.load_official_security2()
            self.assertEqual(str(context.exception), "espidf_source_not_found")

    def test_already_imported_thirdparty_proto_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for rel in loader._REQUIRED:
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# offline fake\n")
            foreign_proto = types.ModuleType("proto")
            foreign_proto.__file__ = "/unrelated/site-packages/proto/__init__.py"
            original = sys.modules.get("proto")
            try:
                sys.modules["proto"] = foreign_proto
                with patch.dict(os.environ, {"IDF_PATH": folder}, clear=True):
                    with self.assertRaises(loader.LabPrerequisiteError) as context:
                        loader.load_official_security2()
                self.assertEqual(
                    str(context.exception), "espidf_module_namespace_conflict"
                )
                self.assertNotIn(str(root / "tools/esp_prov"), sys.path)
            finally:
                if original is None:
                    sys.modules.pop("proto", None)
                else:
                    sys.modules["proto"] = original

    def test_missing_security2_implementation_fails_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for rel in loader._REQUIRED:
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# no Security2 here\n")
            with patch.dict(os.environ, {"IDF_PATH": folder}, clear=True):
                with patch.dict(sys.modules, {
                    "proto": None, "utils": None, "security": None,
                }):
                    # A real integration must reject a broken or incomplete
                    # installation, not fall back to Security0 or Security1.
                    with self.assertRaises(loader.LabPrerequisiteError):
                        loader.load_official_security2()
            self.assertNotIn(str(root / "tools/esp_prov"), sys.path)


if __name__ == "__main__":
    unittest.main()
