"""Backup retention, integrity, and draft-only recovery regressions.

Exercises the existing HA .storage format with a memory-backed Store stub;
no firmware writes or Home Assistant server are needed for these tests.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_backup_history_tests"
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
module = types.ModuleType("homeassistant.helpers.storage")


class StubStore:
    def __init__(self, hass, version, key):
        self.hass = hass
        self.key = key

    async def async_load(self):
        return deepcopy(self.hass.get(self.key))

    async def async_save(self, value):
        self.hass[self.key] = deepcopy(value)


module.Store = StubStore
sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
sys.modules.setdefault("homeassistant.helpers", types.ModuleType("homeassistant.helpers"))
sys.modules["homeassistant.helpers.storage"] = module
backup = load("backup_history")
workspace = load("workspace_store")


def files():
    return {
        "Scenes.json": '{"Scenes":[{"SceneName":"TV","FileName":"Scenes/TV.json"}]}',
        "Scenes/TV.json": '{"ScreenName":"TV","Pages":[]}',
        "Commands/TV.json": '{"Commands":[{"Command":"POWER","Mode":"IR","Protocol":"NEC","Data":["0x1"]}]}',
    }


class FakeApi:
    def __init__(self, docs=None):
        self.docs = docs or files()
        self.calls = []
        self.fail = None

    async def status(self):
        self.calls.append("status")
        return {"api": "omote-config-v1"}

    async def files(self):
        self.calls.append("files")
        return list(self.docs)

    async def read_file(self, path, *, verify_json=False):
        self.calls.append(("read", path, verify_json))
        if self.fail == path:
            raise RuntimeError("Simulated partial transfer")
        return self.docs[path]


class TestBackupHistory(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = {}
        self.store = backup.OmoteBackupHistory(self.hass, "remote_a")
        self.api = FakeApi()

    async def test_capture_lists_only_metadata(self):
        snapshot = await self.store.capture(self.api)
        self.assertEqual(snapshot["file_count"], 3)
        self.assertEqual(snapshot["sha256"], model.file_digest(files()))
        listing = await self.store.list_metadata()
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["integrity"], "verified")
        self.assertNotIn("files", listing[0])
        self.assertNotIn("Commands", str(listing))
        self.assertTrue(all(
            call[2] is True for call in self.api.calls if isinstance(call, tuple)
        ))

    async def test_retains_latest_three_in_original_storage_format(self):
        for number in range(5):
            self.api.docs["Scenes/TV.json"] = (
                '{"ScreenName":"TV%02d","Pages":[]}' % number
            )
            await self.store.capture(self.api)
        record = self.hass["omote_manager.backups_remote_a"]
        self.assertEqual(len(record["snapshots"]), 3)
        listing = await self.store.list_metadata()
        self.assertEqual([item["index"] for item in listing], [2, 1, 0])
        self.assertEqual(listing[0]["sha256"], record["snapshots"][2]["sha256"])
        self.assertEqual(
            model.parse_jsonc(record["snapshots"][0]["files"]["Scenes/TV.json"])["ScreenName"],
            "TV02",
        )

    async def test_failed_capture_preserves_backup_history(self):
        await self.store.capture(self.api)
        existing = deepcopy(self.hass)
        self.api.fail = "Commands/TV.json"
        with self.assertRaisesRegex(RuntimeError, "partial transfer"):
            await self.store.capture(self.api)
        self.assertEqual(self.hass, existing)

    async def test_corrupt_backup_detected_and_blocked(self):
        await self.store.capture(self.api)
        self.hass["omote_manager.backups_remote_a"]["snapshots"][0][
            "files"]["Scenes.json"] = '{"Scenes":'
        listing = await self.store.list_metadata()
        self.assertEqual(listing[0]["integrity"], "damaged")
        with self.assertRaises(model.WorkspaceError):
            await self.store.load_snapshot(0, listing[0]["sha256"])

    async def test_recovery_into_local_draft_without_live_remote(self):
        await self.store.capture(self.api)
        saved = (await self.store.list_metadata())[0]
        saved_files = await self.store.load_snapshot(saved["index"], saved["sha256"])
        draft = workspace.WorkspaceStore(self.hass)
        await draft.async_load()
        await draft.async_import(0, "remote_a", saved_files)
        self.assertEqual(draft.summary()["drafts"]["remote_a"]["file_count"], 3)
        self.assertEqual(draft.summary()["revision"], 1)
        self.assertEqual(saved_files, files())
        with self.assertRaisesRegex(model.WorkspaceError, "already exists"):
            await draft.async_import(1, "remote_a", saved_files)
        # Replacing a local draft is a separate explicitly confirmed operation.
        await draft.async_import(1, "remote_a", saved_files, replace=True)
        self.assertEqual(draft.summary()["revision"], 2)

    async def test_snapshot_index_and_hash_guard(self):
        await self.store.capture(self.api)
        meta = (await self.store.list_metadata())[0]
        with self.assertRaisesRegex(model.WorkspaceError, "Selected backup changed"):
            await self.store.load_snapshot(0, "0" * 64)
        with self.assertRaisesRegex(model.WorkspaceError, "not found"):
            await self.store.load_snapshot(99, meta["sha256"])

    async def test_known_credentials_excluded(self):
        self.api.docs["HaSettings.json"] = '{"Token":"secret"}'
        self.api.docs["Pages/ftp.json"] = '{"Password":"secret"}'
        await self.store.capture(self.api)
        for item in self.hass["omote_manager.backups_remote_a"]["snapshots"][0]["files"]:
            self.assertNotIn("HaSettings", item)
            self.assertNotIn("ftp.json", item)
        self.assertEqual(len(await self.store.list_metadata()), 1)

    async def test_backward_compatible_with_legacy_snapshot(self):
        legacy_files = files()
        self.hass["omote_manager.backups_remote_a"] = {
            "snapshots": [{
                "created_at": "2026-10-31T10:00:00+00:00",
                "files": legacy_files,
                "sha256": model.file_digest(legacy_files),
            }]
        }
        result = await self.store.list_metadata()
        self.assertEqual(result[0]["integrity"], "verified")
        self.assertEqual(
            await self.store.load_snapshot(0, result[0]["sha256"]), legacy_files
        )

    async def test_per_remote_isolation(self):
        await self.store.capture(self.api)
        other = backup.OmoteBackupHistory(self.hass, "remote_b")
        self.assertEqual(await other.list_metadata(), [])
        with self.assertRaisesRegex(model.WorkspaceError, "not found"):
            await other.load_snapshot(0, model.file_digest(files()))

    async def test_oversize_and_invalid_backup_rejected(self):
        self.api.docs["Commands/large.json"] = '{"value":"' + "a" * (65 * 1024) + '"}'
        with self.assertRaisesRegex(model.WorkspaceError, "64 KiB"):
            await self.store.capture(self.api)
        self.assertEqual(await self.store.list_metadata(), [])


if __name__ == "__main__":
    unittest.main()
