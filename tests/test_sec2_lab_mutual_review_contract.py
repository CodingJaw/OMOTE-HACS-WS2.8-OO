"""Pin the firmware LAB-only dual-key proof review contract.

No Home Assistant runtime pairing transport, public PIN entry, network reset,
NVS trusted peer enrollment, or configuration write is implemented here.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/sec2_lab_mutual_review_contract.json"


class LabMutualReviewContract(unittest.TestCase):
    def test_firmware_shared_contract_if_available(self):
        local = json.loads(FIXTURE.read_text())
        path = os.environ.get("OMOTE_FIRMWARE_LAB_MUTUAL_REVIEW_CONTRACT")
        if path:
            self.assertEqual(local, json.loads(Path(path).read_text()))

    def test_mutual_proof_review_remains_non_authorizing(self):
        data = json.loads(FIXTURE.read_text())
        self.assertEqual(data["contract"], "omote-sec2-lab-mutual-review-v1")
        self.assertEqual(data["transport"]["port"], 18082)
        self.assertTrue(data["transport"]["local_start_required"])
        self.assertEqual(data["transport"]["ha_endpoint"], "omote-ha-proof")
        self.assertEqual(data["transport"]["device_endpoint"], "omote-device-proof")
        self.assertTrue(data["review"]["require_exact_same_security2_session_id"])
        self.assertTrue(data["review"]["require_full_sha256_ha_fingerprint_on_touchscreen"])
        self.assertTrue(data["review"]["volatile_only"])
        self.assertTrue(data["review"]["one_shot_review"])
        self.assertEqual(data["review"]["touch_review_deadline_ms"], 60000)
        self.assertEqual(data["review"]["local_approval_label"], "Review OK")
        self.assertEqual(data["review"]["local_reject_label"], "Reject")
        self.assertTrue(all(value is False for value in data["authorization"].values()))
        self.assertEqual(data["rejection"]["session_mismatch"], "fail_closed")
        self.assertEqual(data["rejection"]["duplicate_proof"], "fail_closed")

    def test_hacs_does_not_connect_to_lab_listener_or_enroll_peer(self):
        api = (ROOT / "custom_components/omote_manager/api.py").read_text()
        pairing = (ROOT / "custom_components/omote_manager/pairing_model.py").read_text()
        panel = (ROOT / "custom_components/omote_manager/panel.py").read_text()
        self.assertNotIn("omote-ha-proof", api)
        self.assertNotIn("omote-device-proof", api)
        self.assertNotIn("18082", api)
        self.assertIn('"pairing_enabled": False', pairing)
        self.assertIn('"device_identity_verified": False', pairing)
        self.assertIn('info["deployment_enabled"] = False', panel)


if __name__ == "__main__":
    unittest.main()
