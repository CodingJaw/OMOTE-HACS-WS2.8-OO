"""Firmware-native widget geometry tests for Waveshare 240x320 layout preview."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_geometry_tests"
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
base = load("workspace_model")
layout = load("layout_model")
editor = load("editor_model")


def sample():
    dump = base.dump_json
    return {
        "Scenes.json": dump({"Scenes": [
            {"SceneName": "TV", "FileName": "Scenes/TV.json"}
        ]}),
        "Scenes/TV.json": dump({"ScreenName": "TV", "Pages": [
            {"PageName": "Watch TV", "ShortName": "TV", "FileName": "Pages/TV.json"}
        ]}),
        "Pages/TV.json": dump({
            "CommandFile": "Commands/TV.json",
            "Widgets": [
                {"Type": "Title", "HeightPct": 8, "AlignTo": 0},
                {"Type": "Button", "Text": "Source", "Command": "SOURCE",
                 "HeightPct": 12, "AlignTo": 0, "Custom": "keep"},
                {"Type": "Button", "Text": "Up", "Command": "UP", "SizeXY": [40, 10],
                 "PosX": 30, "PosY": 40},
                {"Type": "ColorButtons", "Command": ["RED", "BLUE"], "AlignTo": 2},
                {"Type": "Image", "FileName": "images/room.png",
                 "SizeXYinPixels": [80, 40], "PosX": 5, "PosY": 60},
                {"Type": "HaToggle", "EntityId": "light.lounge", "AlignTo": 4},
            ],
        }),
        "Commands/TV.json": dump({"Commands": [
            {"Command": name, "Mode": "IR", "Protocol": "NEC", "Data": ["0x01"]}
            for name in ["SOURCE", "UP", "RED", "BLUE"]
        ]}),
    }


def settings(**overrides):
    values = {
        "mode": "absolute", "align_to": 0, "x_pct": 22, "y_pct": 40,
        "width_pct": 50, "height_pct": 12
    }
    values.update(overrides)
    return values


class TestLayoutModel(unittest.TestCase):
    def test_scene_detail_returns_original_percent_geometry(self):
        widgets = editor.scene_detail(sample(), "Scenes/TV.json")["pages"][0]["widgets"]
        self.assertEqual(widgets[2]["layout"]["mode"], "absolute")
        self.assertEqual(widgets[2]["layout"]["x_pct"], 30)
        self.assertEqual(widgets[2]["layout"]["y_pct"], 40)
        self.assertEqual(widgets[2]["layout"]["width_pct"], 40)
        self.assertEqual(widgets[2]["layout"]["height_pct"], 10)
        self.assertTrue(widgets[4]["layout"]["can_position"])
        self.assertFalse(widgets[4]["layout"]["can_size_pct"])

    def test_percent_position_uses_documented_json_fields_and_unknown_keys_survive(self):
        original = sample()
        updated = editor.edit_widget_layout(
            original, "Scenes/TV.json", 0, 1, settings()
        )
        result = base.parse_jsonc(updated["Pages/TV.json"])["Widgets"][1]
        self.assertEqual(result["PosX"], 22)
        self.assertEqual(result["PosY"], 40)
        self.assertEqual(result["SizeXY"], [50, 12])
        self.assertNotIn("AlignTo", result)
        self.assertNotIn("HeightPct", result)
        self.assertEqual(result["Custom"], "keep")
        self.assertEqual(original["Scenes/TV.json"], updated["Scenes/TV.json"])
        self.assertEqual(base.validate_bundle(updated), [])

    def test_align_and_flow_remove_conflicting_position_fields(self):
        original = sample()
        aligned = editor.edit_widget_layout(
            original, "Scenes/TV.json", 0, 2,
            settings(mode="align", align_to=1, width_pct=40, height_pct=10)
        )
        result = base.parse_jsonc(aligned["Pages/TV.json"])["Widgets"][2]
        self.assertEqual(result["AlignTo"], 1)
        self.assertNotIn("PosX", result)
        self.assertNotIn("PosY", result)
        flow = editor.edit_widget_layout(
            aligned, "Scenes/TV.json", 0, 2,
            settings(mode="flow", width_pct=None, height_pct=None)
        )
        result = base.parse_jsonc(flow["Pages/TV.json"])["Widgets"][2]
        self.assertNotIn("AlignTo", result)
        self.assertNotIn("SizeXY", result)
        self.assertNotIn("PosX", result)
        self.assertNotIn("HeightPct", result)

    def test_width_only_becomes_size_xy_with_zero_second_dimension(self):
        changed = editor.edit_widget_layout(
            sample(), "Scenes/TV.json", 0, 1,
            settings(width_pct=75, height_pct=None)
        )
        widget = base.parse_jsonc(changed["Pages/TV.json"])["Widgets"][1]
        self.assertEqual(widget["SizeXY"], [75, 0])

    def test_firmware_sub_10_percent_height_is_preserved(self):
        # JsonPage.cpp raises this to 10% at runtime; config accepts 8%.
        changed = editor.edit_widget_layout(
            sample(), "Scenes/TV.json", 0, 1,
            settings(width_pct=None, height_pct=8)
        )
        widget = base.parse_jsonc(changed["Pages/TV.json"])["Widgets"][1]
        self.assertEqual(widget["HeightPct"], 8)

    def test_height_only_uses_heightpct(self):
        changed = editor.edit_widget_layout(
            sample(), "Scenes/TV.json", 0, 1,
            settings(width_pct=None, height_pct=11)
        )
        widget = base.parse_jsonc(changed["Pages/TV.json"])["Widgets"][1]
        self.assertEqual(widget["HeightPct"], 11)
        self.assertNotIn("SizeXY", widget)

    def test_label_no_absolute_position(self):
        with self.assertRaisesRegex(base.WorkspaceError, "do not support PosX"):
            layout.update_widget_layout(
                {"Type":"Label", "Text":"Hello"},
                settings(width_pct=None, height_pct=8), 1
            )
        updated = layout.update_widget_layout(
            {"Type":"Label", "Text":"Hello", "HeightPct":8},
            settings(mode="align", align_to=0, width_pct=None, height_pct=8),
            2
        )
        self.assertEqual(updated["AlignTo"], 0)
        self.assertEqual(updated["HeightPct"], 8)

    def test_image_retains_pixel_dimensions(self):
        raw = {"Type":"Image", "SizeXYinPixels":[80,40], "PosX":0}
        with self.assertRaisesRegex(base.WorkspaceError, "pixel dimensions"):
            layout.update_widget_layout(raw, settings(), 3)
        result = layout.update_widget_layout(
            raw, settings(width_pct=None, height_pct=None), 3
        )
        self.assertEqual(result["SizeXYinPixels"], [80,40])
        self.assertEqual(result["PosX"], 22)

    def test_invalid_inputs_and_future_widget_alignment_rejected(self):
        original = sample()
        for opts in [
            settings(x_pct=101),
            settings(y_pct=-1),
            settings(align_to=5, mode="align"),
            settings(width_pct=0),
            settings(height_pct=101),
            settings(mode="other"),
        ]:
            with self.subTest(opts=opts), self.assertRaises(base.WorkspaceError):
                editor.edit_widget_layout(original, "Scenes/TV.json", 0, 1, opts)
        self.assertEqual(base.parse_jsonc(original["Pages/TV.json"])["Widgets"][1]["AlignTo"], 0)

    def test_diff_and_revert_still_work(self):
        before = sample()
        after = editor.edit_widget_layout(
            before, "Scenes/TV.json", 0, 2, settings()
        )
        diff = editor.draft_diff(after, before, "Pages/TV.json")
        self.assertIn("PosX", diff["diff"])
        reverted = editor.revert_draft_file(after, before, "Pages/TV.json")
        self.assertEqual(reverted, before)

    def test_imported_data_not_mutated(self):
        obj = {"Type": "Button", "Text": "Test", "HeightPct": 12}
        changed = layout.update_widget_layout(
            obj, settings(mode="align", align_to=0), 1
        )
        self.assertNotIn("AlignTo", obj)
        self.assertNotEqual(obj, changed)


if __name__ == "__main__":
    unittest.main()
