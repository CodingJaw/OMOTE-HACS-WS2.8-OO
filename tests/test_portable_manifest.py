"""Canonical sorted JSON-only review index tests."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_portable_index_test"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package


def load(name):
    spec = importlib.util.spec_from_file_location(PKG + "." + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load("const")
load("safe_files")
model = load("workspace_model")
portable = load("portable_manifest")


def bundle():
    return {
        "Scenes.json": '{"Scenes":[{"FileName":"Scenes/TV.json"}]}',
        "Scenes/TV.json": '{"Pages":[]}',
    }


class TestPortableIndex(unittest.TestCase):
    def test_order_and_exact_utf8_hashes(self):
        files = bundle()
        a = portable.make_portable_index(files)
        b = portable.make_portable_index(dict(reversed(list(files.items()))))
        self.assertEqual(a, b)
        self.assertEqual([x["path"] for x in a["files"]], sorted(files))
        self.assertEqual(a["total_bytes"], sum(len(x.encode()) for x in files.values()))
        for item in a["files"]:
            self.assertEqual(item["sha256"], hashlib.sha256(
                files[item["path"]].encode("utf-8")
            ).hexdigest())
        self.assertFalse(a["complete_for_firmware_deployment"])
        self.assertFalse(a["deployment_enabled"])
        self.assertFalse(a["image_assets_included"])

    def test_private_paths_and_missing_references_rejected(self):
        for changed in [
            dict(bundle(), **{"HaSettings.json": '{"secret":"x"}'}),
            {"Scenes.json": '{"Scenes":[{"FileName":"Scenes/missing.json"}]}'},
            {"Scenes/TV.json": '{"Pages":[]}'},
        ]:
            with self.subTest(files=changed), self.assertRaises(model.WorkspaceError):
                portable.make_portable_index(changed)


if __name__ == "__main__":
    unittest.main()
