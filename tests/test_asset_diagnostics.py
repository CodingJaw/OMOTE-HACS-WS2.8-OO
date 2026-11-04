"""Read-only PNG/JPEG diagnostics: live read, failures, quotas and no writes."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_asset_diagnostics_tests"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package


def load(name):
    spec = importlib.util.spec_from_file_location(PKG + "." + name, ROOT / (name + ".py"))
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    return obj


load("const")
load("safe_files")
model = load("workspace_model")
load("single_active_manifest")
load("asset_inventory")
api_module = load("api")
diag = load("asset_diagnostics")

INDEX = '{"Scenes":[{"SceneName":"TV","FileName":"Scenes/TV.json"}]}'
SCENE = '{"Pages":[{"FileName":"Pages/TV.json"}]}'
PNG = b"\x89PNG\r\n\x1a\n" + b"test"
JPG = b"\xff\xd8\xff" + b"test"


def page(path):
    return '{"Widgets":[{"Type":"Image","FileName":"' + path + '"}]}'


class FakeApi:
    def __init__(self, reference=None, images=None):
        self.json = {
            "Scenes.json": INDEX, "Scenes/TV.json": SCENE,
            "Pages/TV.json": page(reference) if reference else '{"Widgets":[]}',
        }
        self.images = {} if images is None else images
        self.calls = []
        self.fail = set()

    async def status(self):
        return {"api": "omote-config-v1"}

    async def files(self):
        return sorted([*self.json, *self.images])

    async def read_file(self, path, *, verify_json=False):
        self.calls.append(("json", path))
        return self.json[path]

    async def read_image_asset(self, path):
        self.calls.append(("image", path))
        if path in self.fail:
            raise api_module.OmoteApiError("Simulated chunk failure")
        return self.images[path]


class ImageDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_png_and_jpeg_metadata_only(self):
        obj = FakeApi("Images/cover.png", {
            "Images/cover.png": PNG, "Images/other.jpg": JPG,
        })
        report = await diag.inspect_remote_images(obj)
        self.assertEqual(report["referenced_count"], 1)
        self.assertEqual(report["discovered_count"], 2)
        self.assertEqual(report["verified_count"], 2)
        self.assertEqual(report["failed_count"], 0)
        self.assertTrue(report["complete_references"])
        self.assertEqual(len(report["assets"][0]["sha256"]), 64)
        self.assertTrue(any(not x["referenced"] for x in report["assets"]))
        self.assertFalse(report["complete_backup"])
        self.assertFalse(report["deployment_enabled"])
        self.assertTrue(report["read_only"])
        self.assertEqual([x for x in obj.calls if x[0] == "image"],
                         [("image", "Images/cover.png"), ("image", "Images/other.jpg")])

    async def test_missing_reference_is_reported_not_read(self):
        obj = FakeApi("Images/missing.jpg")
        report = await diag.inspect_remote_images(obj)
        self.assertEqual(report["unverified_references"], 1)
        self.assertFalse(report["complete_references"])
        self.assertIn("missing", report["assets"][0]["error"])
        self.assertFalse(any(call[0] == "image" for call in obj.calls))

    async def test_no_images_is_explicitly_not_tested(self):
        report = await diag.inspect_remote_images(FakeApi())
        self.assertEqual(report["checked_count"], 0)
        self.assertIn("NOT TESTED", report["note"])

    async def test_unsafe_reference_never_requested(self):
        obj = FakeApi("Images/../DeviceSettings.jpg")
        report = await diag.inspect_remote_images(obj)
        self.assertEqual(report["failed_count"], 1)
        self.assertIn("Invalid", report["assets"][0]["error"])
        self.assertFalse(any(call[0] == "image" for call in obj.calls))

    async def test_failed_transfer_does_not_claim_verified(self):
        obj = FakeApi("Images/a.jpg", {"Images/a.jpg": JPG})
        obj.fail.add("Images/a.jpg")
        report = await diag.inspect_remote_images(obj)
        self.assertEqual(report["verified_count"], 0)
        self.assertEqual(report["unverified_references"], 1)
        self.assertIn("chunk failure", report["assets"][0]["error"])

    async def test_more_than_64_images_rejected_without_reads(self):
        obj = FakeApi(images={"Images/img%d.jpg" % i: JPG for i in range(65)})
        with self.assertRaisesRegex(model.WorkspaceError, "64 image"):
            await diag.inspect_remote_images(obj)
        self.assertFalse(any(call[0] == "image" for call in obj.calls))

    async def test_total_image_quota_not_claimed_complete(self):
        body = b"\xff\xd8\xff" + b"X" * (512 * 1024 - 3)
        obj = FakeApi(images={"Images/asset%02d.jpg" % i: body for i in range(9)})
        report = await diag.inspect_remote_images(obj)
        self.assertEqual(report["verified_count"], 8)
        self.assertEqual(report["failed_count"], 1)
        self.assertIn("4 MiB", report["assets"][-1]["error"])

    async def test_json_parse_failure_stops_before_image_read(self):
        obj = FakeApi(images={"Images/a.jpg": JPG})
        obj.json["Scenes.json"] = "not json"
        with self.assertRaises(model.WorkspaceError):
            await diag.inspect_remote_images(obj)
        self.assertFalse(any(call[0] == "image" for call in obj.calls))


if __name__ == "__main__":
    unittest.main()
