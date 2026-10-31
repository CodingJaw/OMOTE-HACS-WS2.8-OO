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


if __name__ == "__main__":
    unittest.main()
