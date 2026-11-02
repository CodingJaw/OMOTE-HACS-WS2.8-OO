"""HA-only retained reviewed configuration regressions (no device writes)."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_reviewed_test"
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
storage = types.ModuleType("homeassistant.helpers.storage")


class MemoryStore:
    def __init__(self, hass, version, key):
        self.hass = hass
        self.key = key

    async def async_load(self):
        return deepcopy(self.hass.get(self.key))

    async def async_save(self, data):
        self.hass[self.key] = deepcopy(data)


storage.Store = MemoryStore
sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
sys.modules.setdefault("homeassistant.helpers", types.ModuleType("homeassistant.helpers"))
sys.modules["homeassistant.helpers.storage"] = storage
store_module = load("workspace_store")


def original():
    return {
        "Scenes.json": '{"Scenes":[{"SceneName":"TV","FileName":"Scenes/TV.json"}]}',
        "Scenes/TV.json": '{"ScreenName":"TV","Pages":[]}',
    }


def edited():
    files = original()
    files["Scenes/TV.json"] = '{"ScreenName":"Living room","Pages":[]}'
    return files


class TestRetainedReviewed(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = {}
        self.store = store_module.WorkspaceStore(self.hass)
        await self.store.async_load()
        await self.store.async_import(0, "remote-1", original())
        # Mimic an ordinary local-only draft edit without invoking a device.
        await self.store._mutate(1, lambda state: state["drafts"]["remote-1"].update(
            {"files": edited()}
        ))

    async def test_review_is_immutable_and_backup_history_independent(self):
        digest = model.file_digest(edited())
        result = await self.store.async_save_reviewed(
            2, "remote-1", digest, live_checked=True
        )
        self.assertEqual(result["sha256"], digest)
        self.assertEqual(result["review_status"], "remote-checked")
        self.assertTrue(result["matches_current_draft"])
        self.assertNotIn("files", result)
        self.assertEqual(self.store.reviewed_snapshot("remote-1"), edited())
        # Reimport is explicitly allowed and does not discard the reviewed copy.
        await self.store.async_import(3, "remote-1", original(), replace=True)
        summary = self.store.summary()["reviewed"]["remote-1"]
        self.assertFalse(summary["matches_current_draft"])
        self.assertEqual(self.store.reviewed_snapshot("remote-1"), edited())
        self.assertNotIn("omote_manager.backups_remote-1", self.hass)

    async def test_optimistic_revision_and_hash_required(self):
        with self.assertRaisesRegex(model.WorkspaceError, "Workspace changed"):
            await self.store.async_save_reviewed(
                1, "remote-1", model.file_digest(edited()), live_checked=True
            )
        with self.assertRaisesRegex(model.WorkspaceError, "Draft changed"):
            await self.store.async_save_reviewed(
                2, "remote-1", "0" * 64, live_checked=False
            )
        self.assertEqual(self.store.summary()["revision"], 2)
        self.assertEqual(self.store.summary()["reviewed"], {})

    async def test_unchanged_valid_import_can_be_retained_for_recovery(self):
        await self.store.async_import(2, "remote-1", original(), replace=True)
        result = await self.store.async_save_reviewed(
            3, "remote-1", model.file_digest(original()), live_checked=False
        )
        self.assertEqual(result["sha256"], model.file_digest(original()))
        self.assertEqual(result["review_status"], "offline-unverified")
        self.assertEqual(self.store.reviewed_snapshot("remote-1"), original())

    async def test_offline_review_labeled_unverified(self):
        meta = await self.store.async_save_reviewed(
            2, "remote-1", model.file_digest(edited()), live_checked=False
        )
        self.assertEqual(meta["review_status"], "offline-unverified")
        self.assertFalse(meta["review_status"] == "remote-checked")

    async def test_corrupt_review_fails_closed(self):
        await self.store.async_save_reviewed(
            2, "remote-1", model.file_digest(edited()), live_checked=True
        )
        self.store._state["reviewed"]["remote-1"]["files"]["Scenes/TV.json"] += " "
        self.assertEqual(
            self.store.summary()["reviewed"]["remote-1"]["integrity"], "damaged"
        )
        with self.assertRaisesRegex(model.WorkspaceError, "damaged"):
            self.store.reviewed_snapshot("remote-1")

    async def test_legacy_workspace_record_migrates_in_memory(self):
        self.hass["omote_manager.workspace"] = {
            "schema_version": 1, "revision": 4,
            "locations": [], "templates": [], "drafts": {}
        }
        loaded = store_module.WorkspaceStore(self.hass)
        await loaded.async_load()
        self.assertEqual(loaded.summary()["reviewed"], {})
        self.assertEqual(loaded.summary()["revision"], 4)


if __name__ == "__main__":
    unittest.main()
