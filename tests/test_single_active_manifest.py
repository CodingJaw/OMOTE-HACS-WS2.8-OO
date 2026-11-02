"""Single-active, JSON-only canonical manifest regression tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_single_active_manifest_tests"
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
preview = load("single_active_manifest")


def fixture():
    return {
        "Scenes.json": '{"Scenes":[{"SceneName":"TV","FileName":"Scenes/TV.json"}]}',
        "Scenes/TV.json": '{"Pages":[{"FileName":"Pages/TV.json"}]}',
        "Pages/TV.json": '{"CommandFile":"Commands/TV.json","Widgets":[{"Type":"Button","Command":"POWER"}]}',
        "Commands/TV.json": '{"Commands":[{"Command":"POWER","Mode":"IR","Protocol":"NEC","Data":["0x1"]}]}',
    }


class TestSingleActiveManifest(unittest.TestCase):
    def test_exact_sorted_raw_byte_digests_and_manifest_revision(self):
        files = fixture()
        files = dict(reversed(list(files.items())))
        raw, sha = preview.build_canonical_json_manifest(files)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), sha)
        self.assertNotIn(b" ", raw)
        manifest = json.loads(raw)
        self.assertEqual(manifest["format"], "omote-config-generation-v1")
        self.assertEqual(
            [item["path"] for item in manifest["files"]], sorted(files)
        )
        for entry in manifest["files"]:
            data = files[entry["path"]].encode()
            self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(entry["length"], len(data))
        self.assertEqual(
            raw,
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode()
        )
        self.assertFalse(preview.preview_metadata(files)["deployment_enabled"])

    def test_comments_and_unicode_hashed_as_raw_bytes(self):
        files = fixture()
        files["Scenes/TV.json"] = '{"ScreenName":"Café",/*comment*/"Pages":[{"FileName":"Pages/TV.json"}]}'
        raw, _ = preview.build_canonical_json_manifest(files)
        entries = {
            item["path"]: item for item in json.loads(raw)["files"]
        }
        self.assertEqual(
            entries["Scenes/TV.json"]["length"],
            len(files["Scenes/TV.json"].encode("utf-8"))
        )
        self.assertEqual(
            entries["Scenes/TV.json"]["sha256"],
            hashlib.sha256(files["Scenes/TV.json"].encode("utf-8")).hexdigest()
        )

    def test_image_widget_fails_closed_without_binary_asset(self):
        files = fixture()
        files["Pages/TV.json"] = (
            '{"CommandFile":"Commands/TV.json","Widgets":['
            '{"Type":"Image","FileName":"Images/TV.png"}]}'
        )
        self.assertEqual(preview.referenced_images(files), ["Images/TV.png"])
        with self.assertRaisesRegex(model.WorkspaceError, "Image assets"):
            preview.build_canonical_json_manifest(files)
        self.assertFalse(preview.preview_metadata(files)["complete_json_only"])

    def test_malformed_image_widget_not_treated_as_complete(self):
        files = fixture()
        files["Pages/TV.json"] = '{"Widgets":[{"Type":"Image"}]}'
        with self.assertRaisesRegex(model.WorkspaceError, "Image assets"):
            preview.build_canonical_json_manifest(files)

    def test_missing_page_and_secret_rejected(self):
        files = fixture()
        del files["Pages/TV.json"]
        with self.assertRaisesRegex(model.WorkspaceError, "validation errors"):
            preview.build_canonical_json_manifest(files)
        files = fixture()
        files["HaSettings.json"] = '{"Token":"private"}'
        with self.assertRaises(model.WorkspaceError):
            preview.build_canonical_json_manifest(files)


if __name__ == "__main__":
    unittest.main()
