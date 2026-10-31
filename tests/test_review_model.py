"""Draft review and read-only remote drift regression tests."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_review_test"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules[PKG] = pkg


def load(name):
    spec = importlib.util.spec_from_file_location(
        PKG + "." + name, ROOT / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load("const")
load("safe_files")
model = load("workspace_model")
review = load("review_model")


def source_files():
    return {
        "Scenes.json": model.dump_json({
            "Scenes": [{"SceneName": "Watch TV", "FileName": "Scenes/TV.json"}]
        }),
        "Scenes/TV.json": model.dump_json({
            "ScreenName": "TV",
            "Pages": [{"PageName": "TV", "FileName": "Pages/TV.json"}],
        }),
        "Pages/TV.json": model.dump_json({
            "CommandFile": "Commands/TV.json",
            "Widgets": [{"Type": "Button", "Text": "Power", "Command": "POWER"}],
            "ButtonMaps": {"Power": {"Press": "POWER"}},
        }),
        "Commands/TV.json": model.dump_json({
            "Commands": [{
                "Command": "POWER",
                "Mode": "IR",
                "Protocol": "NEC",
                "Data": ["0x40BE30CF"],
            }]
        }),
    }


class TestReview(unittest.TestCase):
    def test_empty_review_is_blocked_without_network(self):
        source = source_files()
        output = review.make_review(source, source)
        self.assertEqual(output["changed_count"], 0)
        self.assertEqual(output["errors"], 0)
        self.assertFalse(output["deployment_enabled"])
        self.assertFalse(output["live_check"]["checked"])
        self.assertIn("No draft changes to review", output["blockers"])

    def test_manifest_has_hashes_and_sizes_not_file_contents(self):
        original = source_files()
        changed = dict(original)
        changed["Pages/TV.json"] = changed["Pages/TV.json"].replace("Power", "Standby")
        result = review.make_review(changed, original)
        self.assertEqual(result["changed_count"], 1)
        entry = result["changed_files"][0]
        self.assertEqual(entry["operation"], "modify")
        self.assertEqual(entry["path"], "Pages/TV.json")
        self.assertEqual(
            entry["before_sha256"],
            hashlib.sha256(original["Pages/TV.json"].encode()).hexdigest(),
        )
        self.assertEqual(
            entry["after_sha256"],
            hashlib.sha256(changed["Pages/TV.json"].encode()).hexdigest(),
        )
        self.assertEqual(entry["before_bytes"], len(original["Pages/TV.json"].encode()))
        self.assertNotIn("text", entry)
        self.assertNotIn("content", entry)
        self.assertFalse(result["deployment_enabled"])

    def test_live_check_matches_original_while_draft_differs(self):
        original = source_files()
        draft = dict(original)
        draft["Pages/TV.json"] = draft["Pages/TV.json"].replace("Power", "Standby")
        base = review.make_review(draft, original)
        result = review.apply_live_results(base, set(original), {
            "Pages/TV.json": original["Pages/TV.json"]
        })
        self.assertTrue(result["live_check"]["matches"])
        self.assertEqual(result["live_check"]["checked_files"], 1)
        self.assertEqual(result["live_check"]["conflicts"], [])
        self.assertFalse(result["deployment_enabled"])

    def test_live_changed_same_byte_length_detected(self):
        original = source_files()
        draft = dict(original)
        draft["Scenes/TV.json"] = draft["Scenes/TV.json"].replace("TV", "Hi")
        base = review.make_review(draft, original)
        live = dict(original)
        live["Scenes/TV.json"] = live["Scenes/TV.json"].replace("TV", "XX")
        result = review.apply_live_results(base, set(live), {
            "Scenes/TV.json": live["Scenes/TV.json"]
        })
        self.assertFalse(result["live_check"]["matches"])
        self.assertIn("hash mismatch", result["live_check"]["conflicts"][0]["reason"])

    def test_new_file_path_collides_with_remote(self):
        original = source_files()
        draft = dict(original)
        draft["Pages/New.json"] = '{"Widgets":[]}'
        base = review.make_review(draft, original)
        result = review.apply_live_results(
            base, set(original) | {"Pages/New.json"}, {}
        )
        self.assertFalse(result["live_check"]["matches"])
        self.assertEqual(result["live_check"]["checked_files"], 0)
        self.assertIn("already exists", result["live_check"]["conflicts"][0]["reason"])

    def test_deleted_original_and_missing_remote_file_detected(self):
        original = source_files()
        draft = dict(original)
        draft.pop("Commands/TV.json")
        base = review.make_review(draft, original)
        self.assertGreater(base["errors"], 0)
        result = review.apply_live_results(
            base, set(original) - {"Commands/TV.json"}, {}
        )
        self.assertFalse(result["live_check"]["matches"])
        self.assertTrue(any(
            "missing" in x["reason"] for x in result["live_check"]["conflicts"]
        ))

    def test_stale_review_never_reports_no_conflicts(self):
        original = source_files()
        draft = dict(original)
        draft["Pages/TV.json"] = draft["Pages/TV.json"].replace("Power", "Standby")
        base = review.make_review(draft, original)
        result = review.apply_live_results(base, set(original), {
            "Pages/TV.json": original["Pages/TV.json"]
        }, stale=True)
        self.assertFalse(result["live_check"]["matches"])
        self.assertIn("Workspace changed", result["live_check"]["conflicts"][-1]["reason"])

    def test_known_credentials_never_enter_plan(self):
        original = source_files()
        draft = dict(original)
        draft["HaSettings.json"] = '{"Token":"dont-transfer"}'
        with self.assertRaises(model.WorkspaceError):
            review.make_review(draft, original)

    def test_corrupt_draft_blocks_review(self):
        original = source_files()
        draft = dict(original)
        draft["Pages/TV.json"] = '{"Widgets": ['
        outcome = review.make_review(draft, original)
        self.assertGreater(outcome["errors"], 0)
        self.assertFalse(outcome["deployment_enabled"])

    def test_rechecking_same_report_is_rejected(self):
        original = source_files()
        draft = dict(original)
        draft["Pages/New.json"] = '{"Widgets":[]}'
        outcome = review.apply_live_results(
            review.make_review(draft, original), set(original), {}
        )
        with self.assertRaises(model.WorkspaceError):
            review.apply_live_results(outcome, set(original), {})


if __name__ == "__main__":
    unittest.main()
