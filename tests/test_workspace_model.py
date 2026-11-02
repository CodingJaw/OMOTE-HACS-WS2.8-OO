"""Regression coverage for the OMOTE Profile Studio pure model and storage."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_workspace_test"
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
    """Store stub preserving JSON-compatible data across an instance's saves."""

    def __init__(self, hass, version, key):
        self.key = key
        self.hass = hass

    async def async_load(self):
        return deepcopy(self.hass.get(self.key))

    async def async_save(self, value):
        self.hass[self.key] = deepcopy(value)


storage.Store = MemoryStore
sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
sys.modules.setdefault("homeassistant.helpers", types.ModuleType("homeassistant.helpers"))
sys.modules["homeassistant.helpers.storage"] = storage
store = load("workspace_store")


def sample_bundle():
    return {
        "Scenes.json": model.dump_json({
            "Scenes": [
                {"SceneName": "Watch TV", "FileName": "Scenes/TV.json",
                 "BindToKey": "TV", "PressType": "Press"}
            ]
        }),
        "Scenes/TV.json": """{
            // A scene containing a physical keypad override
            "Type": "Scene",
            "ScreenName": "Watch TV",
            "Pages": [
              {"PageName":"Lounge", "FileName":"Pages/TV.json", "CommandPrefix":"LOUNGE_"}
            ],
            "StartCommandSequence":[
              {"CommandFile":"Commands/TV.json","Command":"PWR_ON"}
            ]
        }""",
        "Pages/TV.json": model.dump_json({
            "CommandFile": "Commands/TV.json",
            "Widgets": [{"Type": "Button", "Text": "Up", "Command": "VOL_UP"}],
            "ButtonMaps": {"VolUp": {"Press": "VOL_UP"}}
        }),
        "Commands/TV.json": """{
          "Manufacturer":"Example",
          "Commands":[
            {"Command":"LOUNGE_VOL_UP", "Mode":"IR", "Protocol":"NEC",
             "Data":["0x40BE30CF"], "OtherField":"keep"},
            {"Command":"PWR_ON", "Mode":"MQTT", "Protocol":"PUB",
             "Data":["test/tv/power","on"]}
          ]
        }"""
    }


class TestJsonModel(unittest.TestCase):
    def test_json_comments_respect_strings(self):
        obj = model.parse_jsonc('{"url":"http://unit.local/a/*b*/","n":2,/* note */"x":true}//after')
        self.assertEqual(obj["url"], "http://unit.local/a/*b*/")
        self.assertEqual(obj["n"], 2)
        with self.assertRaises(model.WorkspaceError):
            model.parse_jsonc('{"x": 1} /* never ends')

    def test_complete_bundle_validates(self):
        self.assertEqual(model.validate_bundle(sample_bundle()), [])

    def test_duplicate_scene_entry_rejected(self):
        files = sample_bundle()
        index = model.parse_jsonc(files["Scenes.json"])
        index["Scenes"].append(dict(index["Scenes"][0]))
        files["Scenes.json"] = model.dump_json(index)
        msgs = [issue["message"] for issue in model.validate_bundle(files)]
        self.assertTrue(any("Duplicate scene file" in msg for msg in msgs))
        self.assertTrue(any("Duplicate scene name" in msg for msg in msgs))

    def test_unsupported_widgets_error_and_unbundled_image_warning(self):
        files = sample_bundle()
        page = model.parse_jsonc(files["Pages/TV.json"])
        page["Widgets"].append({"Type": "UnknownRemoteWidget"})
        files["Pages/TV.json"] = model.dump_json(page)
        self.assertTrue(any(
            issue["level"] == "error" and "unsupported firmware widget" in issue["message"]
            for issue in model.validate_bundle(files)
        ))
        page["Widgets"][-1] = {"Type": "Image", "FileName": "Images/Wall.png"}
        files["Pages/TV.json"] = model.dump_json(page)
        self.assertTrue(any(
            issue["level"] == "warning" and "not included" in issue["message"]
            for issue in model.validate_bundle(files)
        ))

    def test_invalid_widget_structure_reports_error_instead_of_crashing(self):
        files = sample_bundle()
        page = model.parse_jsonc(files["Pages/TV.json"])
        page["Widgets"] = None
        page["ButtonMaps"] = []
        files["Pages/TV.json"] = model.dump_json(page)
        issues = model.validate_bundle(files)
        self.assertTrue(any("Widgets must be an array" in x["message"] for x in issues))
        self.assertTrue(any("ButtonMaps must be an object" in x["message"] for x in issues))

    def test_invalid_scene_sequence_is_reported(self):
        files = sample_bundle()
        scene = model.parse_jsonc(files["Scenes/TV.json"])
        scene["StartCommandSequence"] = None
        files["Scenes/TV.json"] = model.dump_json(scene)
        issues = model.validate_bundle(files)
        self.assertTrue(any("StartCommandSequence must be an array" in x["message"] for x in issues))

    def test_applying_same_template_twice_is_idempotent(self):
        source = sample_bundle()
        entry, template = model.extract_scene_template(source, "Scenes/TV.json")
        target = {"Scenes.json": '{"Scenes":[]}'}
        applied = model.apply_scene_template(target, entry, template)
        again = model.apply_scene_template(applied, entry, template)
        self.assertEqual(again, applied)

    def test_missing_reference_is_error(self):
        files = sample_bundle()
        files.pop("Pages/TV.json")
        issues = model.validate_bundle(files)
        self.assertTrue(any("Pages/TV.json" in x["message"] for x in issues))

    def test_edit_command_preserves_other_files_and_unknown_keys(self):
        files = sample_bundle()
        edited = model.edit_command(
            files, "Commands/TV.json", "LOUNGE_VOL_UP",
            "IR", "PANASONIC", ["0x400401000405"]
        )
        self.assertEqual(files["Scenes/TV.json"], edited["Scenes/TV.json"])
        old = model.parse_jsonc(files["Commands/TV.json"])
        new = model.parse_jsonc(edited["Commands/TV.json"])
        self.assertEqual(old["Commands"][0]["Protocol"], "NEC")
        self.assertEqual(new["Commands"][0]["OtherField"], "keep")
        self.assertEqual(new["Commands"][0]["Protocol"], "PANASONIC")

    def test_command_validation_rejects_wrong_mqtt_data(self):
        with self.assertRaises(model.WorkspaceError):
            model.edit_command(
                sample_bundle(), "Commands/TV.json", "PWR_ON",
                "MQTT", "PUB", ["topic-only"]
            )

    def test_extract_template_and_copy_to_another_draft(self):
        source = sample_bundle()
        index, files = model.extract_scene_template(source, "Scenes/TV.json")
        self.assertNotIn("Scenes.json", files)
        self.assertIn("Pages/TV.json", files)
        self.assertIn("Commands/TV.json", files)
        target = {"Scenes.json": '{"Scenes": []}'}
        applied = model.apply_scene_template(target, index, files)
        self.assertEqual(model.available_scenes(applied)[0]["name"], "Watch TV")
        self.assertEqual(model.validate_bundle(applied), [])
        self.assertNotIn("Scenes/TV.json", target)

    def test_template_collision_rejected_without_touching_destination(self):
        source = sample_bundle()
        index, files = model.extract_scene_template(source, "Scenes/TV.json")
        target = {"Scenes.json": '{"Scenes": []}', "Commands/TV.json": '{"Commands":[]}'}
        prior = dict(target)
        with self.assertRaises(model.WorkspaceError):
            model.apply_scene_template(target, index, files)
        self.assertEqual(target, prior)

    def test_credential_path_rejected(self):
        files = sample_bundle()
        files["HaSettings.json"] = '{"Token":"secret"}'
        with self.assertRaises(model.WorkspaceError):
            model.check_bundle_limits(files)


class TestWorkspaceStorage(unittest.IsolatedAsyncioTestCase):
    async def test_revision_conflict_and_persistence(self):
        hass = {}
        workspace = store.WorkspaceStore(hass)
        await workspace.async_load()
        home = await workspace.async_create_location(0, "Home")
        lounge = await workspace.async_create_location(1, "Living Room", home)
        self.assertEqual(len(workspace.summary()["locations"]), 2)
        self.assertEqual(workspace.summary()["locations"][1]["parent_id"], home)
        with self.assertRaises(model.WorkspaceError):
            await workspace.async_create_location(1, "Duplicate edit")
        reloaded = store.WorkspaceStore(hass)
        await reloaded.async_load()
        self.assertEqual(reloaded.summary()["revision"], 2)
        self.assertTrue(any(loc["id"] == lounge for loc in reloaded.summary()["locations"]))

    async def test_invalid_import_does_not_replace_existing_draft(self):
        workspace = store.WorkspaceStore({})
        await workspace.async_load()
        good = sample_bundle()
        await workspace.async_import(0, "remote_a", good)
        before = workspace.summary()["drafts"]["remote_a"]
        damaged = dict(good)
        damaged["Commands/TV.json"] = damaged["Commands/TV.json"][:100]
        with self.assertRaisesRegex(model.WorkspaceError, "Invalid imported file"):
            await workspace.async_import(1, "remote_a", damaged, replace=True)
        after = workspace.summary()["drafts"]["remote_a"]
        self.assertEqual(workspace.summary()["revision"], 1)
        self.assertEqual(after, before)

    async def test_templates_shared_between_remote_drafts(self):
        workspace = store.WorkspaceStore({})
        await workspace.async_load()
        source = sample_bundle()
        await workspace.async_import(0, "remote_a", source)
        template = await workspace.async_create_template(
            1, "remote_a", "Scenes/TV.json", "TV template", None
        )
        await workspace.async_import(2, "remote_b", {"Scenes.json": '{"Scenes":[]}'})
        await workspace.async_apply_template(3, "remote_b", template)
        self.assertEqual(workspace.summary()["revision"], 4)
        self.assertEqual(workspace.validation("remote_b")["errors"], 0)
        self.assertGreater(workspace.summary()["drafts"]["remote_b"]["modified_count"], 0)

    async def test_local_command_edits_are_not_live_edits(self):
        workspace = store.WorkspaceStore({})
        await workspace.async_load()
        source = sample_bundle()
        await workspace.async_import(0, "remote_a", source)
        await workspace.async_edit_command(
            1, "remote_a", "Commands/TV.json", "PWR_ON",
            "MQTT", "PUB", ["test/power", "off"]
        )
        self.assertEqual(workspace.summary()["drafts"]["remote_a"]["modified_count"], 1)
        self.assertEqual(
            model.parse_jsonc(source["Commands/TV.json"])["Commands"][1]["Data"][1], "on"
        )
        self.assertEqual(workspace.validation("remote_a")["errors"], 0)


class TestReviewedRetention(unittest.IsolatedAsyncioTestCase):
    async def test_retained_config_independent_of_draft_and_survives_reload(self):
        hass = {}
        ws = store.WorkspaceStore(hass)
        await ws.async_load()
        original = sample_bundle()
        await ws.async_import(0, "remote_a", original)
        digest = model.file_digest(original)
        await ws.async_retain_reviewed(1, "remote_a", digest)
        self.assertEqual(ws.summary()["revision"], 2)
        self.assertEqual(ws.summary()["reviewed"]["remote_a"]["sha256"], digest)
        self.assertFalse(ws.summary()["deployment_enabled"])
        await ws.async_edit_command(
            2, "remote_a", "Commands/TV.json",
            "PWR_ON", "MQTT", "PUB", ["another/topic", "off"]
        )
        self.assertNotEqual(
            ws.summary()["drafts"]["remote_a"]["current_sha256"], digest
        )
        self.assertEqual(ws.summary()["reviewed"]["remote_a"]["sha256"], digest)
        after_restart = store.WorkspaceStore(hass)
        await after_restart.async_load()
        self.assertEqual(after_restart.summary()["reviewed"]["remote_a"]["sha256"], digest)
        with self.assertRaisesRegex(model.WorkspaceError, "explicitly confirm"):
            await after_restart.async_load_reviewed(3, "remote_a", digest)
        await after_restart.async_load_reviewed(3, "remote_a", digest, replace=True)
        self.assertEqual(
            after_restart.summary()["drafts"]["remote_a"]["current_sha256"], digest
        )
        self.assertEqual(after_restart.summary()["revision"], 4)
        self.assertNotIn("files", after_restart.summary()["reviewed"]["remote_a"])

    async def test_reviewed_save_requires_draft_digest_and_valid_graph(self):
        ws = store.WorkspaceStore({})
        await ws.async_load()
        files = sample_bundle()
        await ws.async_import(0, "remote_a", files)
        with self.assertRaisesRegex(model.WorkspaceError, "Draft SHA-256"):
            await ws.async_retain_reviewed(1, "remote_a", "0" * 64)
        self.assertEqual(ws.summary()["revision"], 1)
        invalid = dict(files)
        invalid.pop("Pages/TV.json")
        # Directly exercising mutation is intentional: editing methods normally
        # guard this; review must reject a structurally invalid draft regardless.
        ws._state["drafts"]["remote_a"]["files"] = invalid
        with self.assertRaisesRegex(model.WorkspaceError, "validation errors"):
            await ws.async_retain_reviewed(1, "remote_a", model.file_digest(invalid))
        self.assertNotIn("remote_a", ws.summary()["reviewed"])

    async def test_reviewed_hash_tampering_rejected_before_draft_replacement(self):
        ws = store.WorkspaceStore({})
        await ws.async_load()
        files = sample_bundle()
        await ws.async_import(0, "remote_a", files)
        sha = model.file_digest(files)
        await ws.async_retain_reviewed(1, "remote_a", sha)
        ws._state["reviewed"]["remote_a"]["files"]["Scenes.json"] += " "
        before = ws.summary()["drafts"]["remote_a"]["current_sha256"]
        with self.assertRaisesRegex(model.WorkspaceError, "failed SHA-256"):
            await ws.async_load_reviewed(2, "remote_a", sha, replace=True)
        self.assertEqual(ws.summary()["revision"], 2)
        self.assertEqual(ws.summary()["drafts"]["remote_a"]["current_sha256"], before)

    async def test_legacy_workspace_upgrade_defaults_reviewed(self):
        hass = {
            "omote_manager.workspace": {
                "schema_version": 1, "revision": 3,
                "locations": [], "templates": [], "drafts": {}
            }
        }
        ws = store.WorkspaceStore(hass)
        await ws.async_load()
        self.assertEqual(ws.summary()["reviewed"], {})
        self.assertEqual(ws.summary()["revision"], 3)


if __name__ == "__main__":
    unittest.main()
