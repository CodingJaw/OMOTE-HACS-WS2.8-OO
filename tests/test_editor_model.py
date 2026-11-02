"""Firmware-native scene/page/button editor regression tests (no HA runtime)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_scene_editor_tests"
module = types.ModuleType(PKG)
module.__path__ = [str(ROOT)]
sys.modules[PKG] = module


def load(name):
    spec = importlib.util.spec_from_file_location(
        PKG + "." + name, ROOT / (name + ".py")
    )
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    return obj


load("const")
load("safe_files")
model = load("workspace_model")
editor = load("editor_model")


def fixture():
    """Mirrors OMOTE Waveshare scene/page command structures."""
    dump = model.dump_json
    return {
        "Scenes.json": dump({
            "Scenes": [
                {
                    "SceneName": "Watch TV", "FileName": "Scenes/WatchTV.json",
                    "BindToKey": "TV", "PressType": "Press",
                },
                {
                    "SceneName": "Heating", "FileName": "Scenes/Heating.json",
                    "BindToKey": "Audio", "PressType": "Long",
                },
            ]
        }),
        "Scenes/WatchTV.json": """{
          // The page file may be shared between scene tabs
          "Type":"Scene",
          "ScreenName":"TV",
          "Pages":[{"PageName":"Main TV","ShortName":"TV",
            "FileName":"Pages/TV.json"}],
          "StartCommandSequence":[
            {"CommandFile":"Commands/TV.json","Command":"POWER"}
          ]
        }""",
        "Scenes/Heating.json": dump({
            "Type": "List", "ScreenName": "Heat",
            "Pages": [
                {"PageName":"Heating (Living Room)", "ShortName":"Lounge",
                 "FileName":"Pages/Heating.json", "CommandPrefix":"LOUNGE_"},
                {"PageName":"Heating (Kitchen)", "ShortName":"Kitchen",
                 "FileName":"Pages/Heating.json", "CommandPrefix":"KITCHEN_"},
            ],
        }),
        "Pages/TV.json": dump({
            "CommandFile": "Commands/TV.json",
            "Widgets": [
                {"Type":"Button", "Text":"Input", "Command":"SOURCE", "AlignTo":0},
                {"Type":"ColorButtons", "Command":["RED","BLUE"]},
                {"Type":"HaSwitch", "EntityId":"switch.somewhere"},
            ],
            "ButtonMaps": {
                "Power":{"Press":"POWER"},
                "VolUp":{"Press":"UP","Repeat":"UP"},
            },
        }),
        "Pages/Heating.json": dump({
            "CommandFile":"Commands/Heating.json",
            "Widgets":[{"Type":"Button","Text":"Boost","Command":"BOOST"}],
            "ButtonMaps":{"Up":{"Press":"UP"}},
        }),
        "Commands/TV.json": dump({
            "Manufacturer":"Example",
            "Commands":[
                {"Command":cmd,"Mode":"IR","Protocol":"NEC","Data":["0x1"]}
                for cmd in ("POWER","SOURCE","RED","BLUE","UP","DOWN")
            ],
        }),
        "Commands/Heating.json": dump({
            "Commands":[
                {"Command":prefix + cmd,"Mode":"MQTT",
                 "Protocol":"PUB","Data":["heating/set","1"]}
                for prefix in ("LOUNGE_","KITCHEN_")
                for cmd in ("BOOST","UP")
            ],
        }),
    }


class TestSceneEditing(unittest.TestCase):
    def test_scene_detail_maps_actual_firmware_fields(self):
        files = fixture()
        result = editor.scene_detail(files, "Scenes/WatchTV.json")
        self.assertEqual(result["scene_name"], "Watch TV")
        self.assertEqual(result["bind_to_key"], "TV")
        self.assertEqual(result["pages"][0]["command_options"][0], "BLUE")
        self.assertEqual(result["pages"][0]["button_maps"]["VolUp"]["Repeat"], "UP")
        self.assertFalse(result["pages"][0]["widgets"][2]["editable_command"])

    def test_shared_page_impact_lists_other_scenes(self):
        files = fixture()
        other = model.parse_jsonc(files["Scenes/Heating.json"])
        other["Pages"].append({
            "PageName": "Shared TV controls", "FileName": "Pages/TV.json"
        })
        files["Scenes/Heating.json"] = model.dump_json(other)
        detail = editor.scene_detail(files, "Scenes/WatchTV.json")
        page = detail["pages"][0]
        self.assertEqual(page["shared_scene_count"], 1)
        self.assertEqual(page["shared_with_scenes"], ["Heating"])
        other_detail = editor.scene_detail(files, "Scenes/Heating.json")
        self.assertEqual(other_detail["pages"][2]["shared_with_scenes"], ["Watch TV"])

    def test_prefix_command_options(self):
        detail = editor.scene_detail(fixture(), "Scenes/Heating.json")
        self.assertEqual(detail["pages"][0]["command_options"], ["BOOST","UP"])
        self.assertEqual(detail["pages"][1]["command_options"], ["BOOST","UP"])

    def test_scene_updates_index_and_title_preserving_other_files(self):
        original = fixture()
        edited = editor.edit_scene(
            original, "Scenes/WatchTV.json",
            name="Television", screen_name="Living Room TV",
            bind_key="DVD", press_type="Long",
        )
        self.assertEqual(
            model.parse_jsonc(edited["Scenes.json"])["Scenes"][0]["SceneName"],
            "Television",
        )
        self.assertEqual(
            model.parse_jsonc(edited["Scenes/WatchTV.json"])["ScreenName"],
            "Living Room TV",
        )
        self.assertEqual(
            model.parse_jsonc(edited["Scenes.json"])["Scenes"][0]["PressType"],
            "Long",
        )
        self.assertEqual(edited["Pages/TV.json"], original["Pages/TV.json"])
        self.assertEqual(model.validate_bundle(edited), [])
        self.assertEqual(
            model.parse_jsonc(original["Scenes/WatchTV.json"])["ScreenName"],
            "TV",
        )

    def test_scene_shortcut_and_name_collision_rejected(self):
        original = fixture()
        with self.assertRaisesRegex(model.WorkspaceError, "name"):
            editor.edit_scene(
                original, "Scenes/WatchTV.json",
                name="Heating", screen_name="TV",
                bind_key="TV", press_type="Press",
            )
        with self.assertRaisesRegex(model.WorkspaceError, "key"):
            editor.edit_scene(
                original, "Scenes/WatchTV.json",
                name="Other", screen_name="TV",
                bind_key="Audio", press_type="Long",
            )
        self.assertEqual(model.validate_bundle(original), [])

    def test_scene_removes_shortcut_without_deleting_other_keys(self):
        files = fixture()
        changed = editor.edit_scene(
            files, "Scenes/WatchTV.json",
            name="Watch TV", screen_name="TV",
            bind_key="", press_type="Press",
        )
        entry = model.parse_jsonc(changed["Scenes.json"])["Scenes"][0]
        self.assertNotIn("BindToKey", entry)
        self.assertNotIn("PressType", entry)
        self.assertEqual(entry["SceneName"], "Watch TV")

    def test_page_labels_only_edit_scene_file(self):
        files = fixture()
        modified = editor.edit_page_title(
            files, "Scenes/WatchTV.json", 0,
            name="Main Television", short_name="TV",
        )
        page_ref = model.parse_jsonc(modified["Scenes/WatchTV.json"])["Pages"][0]
        self.assertEqual(page_ref["PageName"], "Main Television")
        self.assertEqual(modified["Pages/TV.json"], files["Pages/TV.json"])

    def test_widget_text_and_array_position(self):
        files = fixture()
        caption = editor.edit_widget(
            files, "Scenes/WatchTV.json", 0, 0,
            field="text", value="HDMI input",
        )
        command = editor.edit_widget(
            caption, "Scenes/WatchTV.json", 0, 1,
            field="command", value="DOWN", command_index=1,
        )
        widgets = model.parse_jsonc(command["Pages/TV.json"])["Widgets"]
        self.assertEqual(widgets[0]["Text"], "HDMI input")
        self.assertEqual(widgets[1]["Command"], ["RED","DOWN"])
        self.assertEqual(widgets[0]["AlignTo"], 0)
        self.assertEqual(model.validate_bundle(command), [])
        self.assertEqual(
            model.parse_jsonc(files["Pages/TV.json"])["Widgets"][0]["Text"], "Input"
        )

    def test_unavailable_or_uneditable_widget_commands_rejected(self):
        files = fixture()
        with self.assertRaisesRegex(model.WorkspaceError, "does not exist"):
            editor.edit_widget(
                files, "Scenes/WatchTV.json", 0, 0,
                field="command", value="NOT_A_COMMAND",
            )
        with self.assertRaisesRegex(model.WorkspaceError, "no editable command"):
            editor.edit_widget(
                files, "Scenes/WatchTV.json", 0, 2,
                field="command", value="POWER",
            )
        with self.assertRaisesRegex(model.WorkspaceError, "Invalid command array"):
            editor.edit_widget(
                files, "Scenes/WatchTV.json", 0, 1,
                field="command", value="RED", command_index=99,
            )

    def test_button_mapping_add_update_remove_and_event_validation(self):
        files = fixture()
        changed = editor.edit_button_map(
            files, "Scenes/WatchTV.json", 0,
            key="Home", event="Long", command="SOURCE",
        )
        events = model.parse_jsonc(changed["Pages/TV.json"])["ButtonMaps"]["Home"]
        self.assertEqual(events, {"Long":"SOURCE"})
        removed = editor.edit_button_map(
            changed, "Scenes/WatchTV.json", 0,
            key="Home", event="Long", command="",
        )
        self.assertNotIn(
            "Home", model.parse_jsonc(removed["Pages/TV.json"])["ButtonMaps"]
        )
        with self.assertRaisesRegex(model.WorkspaceError, "Invalid physical key"):
            editor.edit_button_map(
                files, "Scenes/WatchTV.json", 0,
                key="NotAKey", event="Press", command="UP",
            )
        with self.assertRaisesRegex(model.WorkspaceError, "Unsupported key event"):
            editor.edit_button_map(
                files, "Scenes/WatchTV.json", 0,
                key="Up", event="Tap", command="UP",
            )

    def test_shared_page_changes_are_explicitly_shared(self):
        files = fixture()
        changed = editor.edit_button_map(
            files, "Scenes/Heating.json", 0,
            key="VolUp", event="Repeat", command="BOOST",
        )
        first = editor.scene_detail(changed, "Scenes/Heating.json")["pages"]
        self.assertEqual(first[0]["button_maps"]["VolUp"]["Repeat"], "BOOST")
        self.assertEqual(first[1]["button_maps"]["VolUp"]["Repeat"], "BOOST")
        self.assertEqual(model.validate_bundle(changed), [])

    def test_diff_and_revert_are_local_and_bounded(self):
        files = fixture()
        changed = editor.edit_page_title(
            files, "Scenes/WatchTV.json", 0,
            name="New page title", short_name="TV",
        )
        listing = editor.draft_diff(changed, files)
        self.assertEqual(listing["changed_files"], ["Scenes/WatchTV.json"])
        diff = editor.draft_diff(changed, files, "Scenes/WatchTV.json")
        self.assertIn("+", diff["diff"])
        self.assertIn("New page title", diff["diff"])
        reverted = editor.revert_draft_file(
            changed, files, "Scenes/WatchTV.json"
        )
        self.assertEqual(reverted, files)
        with self.assertRaisesRegex(model.WorkspaceError, "Select a modified"):
            editor.draft_diff(files, files, "Scenes/WatchTV.json")
        with self.assertRaisesRegex(model.WorkspaceError, "unsafe"):
            editor.revert_draft_file(files, files, "HaSettings.json")

    def test_diff_lists_template_added_file_and_revert_removes_it(self):
        imported = fixture()
        draft = dict(imported)
        draft["Pages/New.json"] = '{"Widgets":[]}'
        changes = editor.draft_diff(draft, imported)["changed_files"]
        self.assertIn("Pages/New.json", changes)
        reverted = editor.revert_draft_file(draft, imported, "Pages/New.json")
        self.assertNotIn("Pages/New.json", reverted)
        self.assertIn("Pages/New.json", draft)


if __name__ == "__main__":
    unittest.main()
