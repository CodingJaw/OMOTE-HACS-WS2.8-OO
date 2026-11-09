"""Offline matched Security2 patch1 toolchain contract verification.

This does not create a Home Assistant pairing service or update devices.
"""
from __future__ import annotations
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=json.loads((ROOT/"tests/fixtures/sec2_nonce1_toolchain_candidate_contract.json").read_text())


class Nonce1ToolchainCandidateTests(unittest.TestCase):
    def test_old_working_firmware_is_unmodified(self):
        current=SPEC["current_verified_lab"]
        candidate=SPEC["candidate"]
        self.assertTrue(current["preserve_unchanged"])
        self.assertEqual(current["env"],"waveshare28v2_omote_sec2_tx_v2_lab")
        self.assertEqual(current["security2_patch"],0)
        self.assertEqual(candidate["extends"],current["env"])
        self.assertNotEqual(candidate["env"],current["env"])

    def test_candidate_is_matched_arduino_idf55_patch1(self):
        candidate=SPEC["candidate"]
        self.assertEqual(candidate["platform_tag"],"2026.10.50")
        self.assertEqual(candidate["arduino_core_tag"],"v3.3.12-1")
        self.assertEqual(candidate["esp_idf"],"5.5.5")
        self.assertEqual(candidate["security2_required_patch"],1)
        self.assertTrue(candidate["listener_must_refuse_if_linked_patch_is_not_1"])
        self.assertTrue(candidate["flash_after_compilation_only"])
        self.assertTrue(candidate["board_build_and_runtime_not_yet_verified"])
        self.assertIn("v5.5.5",candidate["esp_idf_platform_package_url"])

    def test_hardware_acceptance_and_no_grants(self):
        required=SPEC["required_tests"]
        for name in ("srp6a_aesgcm_hardware_handshake",
                     "exact_transcript_bound_touchscreen_review",
                     "one_shot_device_signed_touch_receipt",
                     "counter_overflow_fails_closed"):
            self.assertIn(name,required)
        authorization=SPEC["authorization"]
        self.assertTrue(authorization["laboratory_only"])
        self.assertTrue(all(v is False for k,v in authorization.items()
                            if k!="laboratory_only"))

    def test_no_hacs_live_endpoint_registered(self):
        root=ROOT/"custom_components/omote_manager"
        for path in root.glob("*.py"):
            self.assertNotIn("OMOTE_CONFIG_V2_SEC2_NONCE1_LAB",path.read_text(),
                             path.name)


if __name__=="__main__":
    unittest.main()
