"""Offline deployment-kit archive verification and single-active baseline-package tests."""
from __future__ import annotations

from io import BytesIO
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_kit_tests"
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
review = load("review_model")
release = load("release_model")


def fixture():
    dump = model.dump_json
    return {
        "Scenes.json": dump({
            "Scenes": [{"SceneName": "TV", "FileName": "Scenes/TV.json"}]
        }),
        "Scenes/TV.json": dump({
            "Type": "Scene", "ScreenName": "Television",
            "Pages": [{"FileName": "Pages/TV.json", "PageName": "TV"}],
        }),
        "Pages/TV.json": dump({
            "CommandFile": "Commands/TV.json",
            "Widgets": [{"Type": "Button", "Text": "Power", "Command": "POWER"}],
        }),
        "Commands/TV.json": dump({"Commands": [{
            "Command": "POWER", "Mode": "IR", "Protocol": "NEC", "Data": ["0x1"]
        }]}),
    }


def edited_files(original):
    proposal = dict(original)
    proposal["Scenes/TV.json"] = proposal["Scenes/TV.json"].replace(
        "Television", "Living Room Television"
    )
    return proposal


class TestReleaseArchive(unittest.TestCase):
    def test_contains_full_proposal_baseline_manifest_and_instructions(self):
        original = fixture()
        proposal = edited_files(original)
        report = review.make_review(proposal, original)
        archive = release.build_deployment_kit(
            proposal, original, report, remote_id="test-entry-id"
        )
        self.assertTrue(archive.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(archive)) as package:
            names = set(package.namelist())
            self.assertIn("READ_ME_FIRST.txt", names)
            self.assertIn("MANIFEST.json", names)
            for path in original:
                self.assertIn("baseline/" + path, names)
                self.assertIn("proposed/" + path, names)
                self.assertEqual(
                    package.read("baseline/" + path), original[path].encode()
                )
                self.assertEqual(
                    package.read("proposed/" + path), proposal[path].encode()
                )
            self.assertIn("GENERATION_MANIFEST_PREVIEW.json", names)
            canonical = package.read("GENERATION_MANIFEST_PREVIEW.json")
            self.assertEqual(
                json.loads(canonical)["format"], "omote-config-generation-v1"
            )
            self.assertEqual(package.testzip(), None)
            manifest = json.loads(package.read("MANIFEST.json"))
            self.assertEqual(manifest["format"], release.BUNDLE_VERSION)
            self.assertEqual(manifest["changes"], 1)
            self.assertEqual(manifest["entry_id"], "test-entry-id")
            self.assertEqual(manifest["review_status"], "offline_unverified")
            self.assertFalse(manifest["deployable_by_current_integration"])
            self.assertFalse(manifest["automatic_rollback_supported"])
            self.assertTrue(manifest["canonical_manifest_included"])
            self.assertEqual(
                manifest["draft_sha256"], model.file_digest(proposal)
            )
            self.assertEqual(manifest["baseline_file_count"], 4)
            self.assertIn("not an installer",
                          package.read("READ_ME_FIRST.txt").decode().lower())

    def test_verified_archive_tag_only_after_read_only_remote_check(self):
        original = fixture()
        proposal = edited_files(original)
        report = review.apply_live_results(
            review.make_review(proposal, original),
            set(original),
            {"Scenes/TV.json": original["Scenes/TV.json"]},
        )
        archive = release.build_deployment_kit(
            proposal, original, report, remote_id="test-remote"
        )
        with zipfile.ZipFile(BytesIO(archive)) as package:
            manifest = json.loads(package.read("MANIFEST.json"))
            self.assertEqual(
                manifest["review_status"], "remote_verified_at_export"
            )
            self.assertTrue(manifest["remote_check_performed"])

    def test_stale_draft_hash_is_rejected(self):
        original = fixture()
        proposal = edited_files(original)
        report = review.make_review(proposal, original)
        newer = dict(proposal)
        newer["Scenes/TV.json"] = newer["Scenes/TV.json"].replace(
            "Living Room Television", "Guest Television"
        )
        with self.assertRaisesRegex(model.WorkspaceError, "Draft changed"):
            release.build_deployment_kit(
                newer, original, report, remote_id="remote"
            )

    def test_invalid_json_blocks_download(self):
        original = fixture()
        proposal = dict(original)
        proposal["Pages/TV.json"] = '{"Widgets":['
        report = review.make_review(proposal, original)
        self.assertGreater(report["errors"], 0)
        with self.assertRaisesRegex(model.WorkspaceError, "validation"):
            release.build_deployment_kit(
                proposal, original, report, remote_id="remote"
            )

    def test_unchanged_configuration_is_not_a_deployment_kit(self):
        original = fixture()
        report = review.make_review(original, original)
        with self.assertRaisesRegex(model.WorkspaceError, "no draft changes"):
            release.build_deployment_kit(
                original, original, report, remote_id="remote"
            )

    def test_conflicting_live_file_blocks_download(self):
        original = fixture()
        proposal = edited_files(original)
        report = review.apply_live_results(
            review.make_review(proposal, original),
            set(original),
            {"Scenes/TV.json": original["Scenes/TV.json"].replace(
                "Television", "Other Device"
            )},
        )
        self.assertFalse(report["live_check"]["matches"])
        with self.assertRaisesRegex(model.WorkspaceError, "conflicting"):
            release.build_deployment_kit(
                proposal, original, report, remote_id="remote"
            )

    def test_sensitive_and_parent_paths_cannot_enter_zip(self):
        original = fixture()
        for bad_path in ("HaSettings.json", "Pages/../../bad.json",
                         "Devices/DeviceSettings.json", "Pages\\x.json"):
            proposal = edited_files(original)
            proposal[bad_path] = '{"secret":"not allowed"}'
            with self.subTest(bad_path=bad_path), self.assertRaises(model.WorkspaceError):
                release.build_deployment_kit(
                    proposal, original, {"draft_sha256": model.file_digest(proposal)},
                    remote_id="remote"
                )

    def test_baseline_hash_mismatch_is_rejected(self):
        original = fixture()
        proposal = edited_files(original)
        report = review.make_review(proposal, original)
        tampered_baseline = dict(original)
        tampered_baseline["Scenes/TV.json"] += " "
        with self.assertRaisesRegex(model.WorkspaceError, "baseline changed"):
            release.build_deployment_kit(
                proposal, tampered_baseline, report, remote_id="remote"
            )

    def test_additions_and_deletions_present_in_manifest(self):
        original = fixture()
        proposal = edited_files(original)
        proposal["Devices/Speaker.json"] = '{"Brand":"Generic"}'
        proposal.pop("Commands/TV.json")
        report = review.make_review(proposal, original)
        # Deletion causes missing command reference: keep it in the plan,
        # but never allow export until the configuration is repaired.
        self.assertGreater(report["errors"], 0)
        ops = {entry["path"]: entry["operation"]
               for entry in report["changed_files"]}
        self.assertEqual(ops["Devices/Speaker.json"], "add")
        self.assertEqual(ops["Commands/TV.json"], "delete")
        with self.assertRaisesRegex(model.WorkspaceError, "validation"):
            release.build_deployment_kit(
                proposal, original, report, remote_id="remote"
            )

    def test_archive_has_no_executable_entries_or_symlinks(self):
        original = fixture()
        proposal = edited_files(original)
        archive = release.build_deployment_kit(
            proposal, original, review.make_review(proposal, original),
            remote_id="remote"
        )
        with zipfile.ZipFile(BytesIO(archive)) as package:
            for item in package.infolist():
                self.assertTrue(item.filename.endswith((".json", ".txt")))
                self.assertFalse(item.filename.startswith("/"))
                self.assertNotIn("../", item.filename)
                self.assertEqual((item.external_attr >> 16) & 0o170000, 0o100000)
