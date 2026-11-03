"""Image dependency inventory must fail closed until full asset capture exists."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_asset_inventory_tests"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules[PKG] = pkg


def load(name):
    spec = importlib.util.spec_from_file_location(PKG + "." + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load("const")
load("safe_files")
model = load("workspace_model")
load("single_active_manifest")
assets = load("asset_inventory")


def fixture(path="Images/wallpaper.png"):
    return {
        "Scenes.json": '{"Scenes":[{"SceneName":"TV","FileName":"Scenes/TV.json"}]}',
        "Scenes/TV.json": '{"Pages":[{"FileName":"Pages/TV.json"}]}',
        "Pages/TV.json": '{"Widgets":[{"Type":"Image","FileName":"' + path + '"}]}',
    }


class AssetInventoryTests(unittest.TestCase):
    def test_missing_image_is_incomplete(self):
        report = assets.inventory(fixture())
        self.assertFalse(report["complete_assets"])
        self.assertEqual(report["referenced_count"], 1)
        self.assertEqual(report["present_count"], 0)
        self.assertFalse(report["remote_write_enabled"])

    def test_verified_png_image(self):
        data = b"\x89PNG\r\n\x1a\n" + b"example-image-data"
        report = assets.inventory(fixture(), {"Images/wallpaper.png": data})
        self.assertTrue(report["complete_assets"])
        self.assertEqual(report["total_asset_bytes"], len(data))
        self.assertEqual(len(report["assets"][0]["sha256"]), 64)

    def test_jpeg_signature(self):
        report = assets.inventory(
            fixture("Images/room.jpg"), {"Images/room.jpg": b"\xff\xd8\xff" + b"image"}
        )
        self.assertTrue(report["complete_assets"])

    def test_wrong_signature_rejected(self):
        with self.assertRaisesRegex(model.WorkspaceError, "PNG signature"):
            assets.inventory(fixture(), {"Images/wallpaper.png": b"not png"})

    def test_traversal_rejected(self):
        with self.assertRaisesRegex(model.WorkspaceError, "Invalid image asset path"):
            assets.inventory(fixture("Images/../private.png"))

    def test_extra_asset_rejected(self):
        with self.assertRaisesRegex(model.WorkspaceError, "unreferenced"):
            assets.inventory(fixture(), {"Images/other.png": b"\x89PNG\r\n\x1a\nx"})

    def test_oversized_asset_rejected(self):
        with self.assertRaisesRegex(model.WorkspaceError, "size"):
            assets.inventory(fixture(), {
                "Images/wallpaper.png": b"\x89PNG\r\n\x1a\n" + b"x" * assets.MAX_ASSET_BYTES
            })

    def test_no_references_is_complete_but_json_only(self):
        data = fixture()
        data["Pages/TV.json"] = '{"Widgets":[]}'
        report = assets.inventory(data)
        self.assertTrue(report["complete_assets"])
        self.assertEqual(report["referenced_count"], 0)


if __name__ == "__main__":
    unittest.main()
