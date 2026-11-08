"""Verify firmware's LAB-only P-256 local-touch receipt wire contract.

No production Home Assistant pairing, trust, reconnection, or device writes.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT/"tests/fixtures/sec2_tx_v2_signed_touch_receipt_lab_contract.json").read_text())


class SignedTouchLabWireContractTests(unittest.TestCase):
    def test_exact_same_session_receipt_wire(self):
        self.assertEqual(CONTRACT["transport"]["endpoint"],"omote-tx2-touch-receipt")
        self.assertEqual(CONTRACT["transport"]["port"],18082)
        self.assertEqual(CONTRACT["request"]["bytes"],65)
        self.assertEqual(CONTRACT["response"]["minimum_bytes"],11)
        self.assertEqual(CONTRACT["response"]["maximum_bytes"],83)
        self.assertEqual(CONTRACT["signature"]["domain"],
                         "OMOTE-SEC2-TX2-TOUCH-RECEIPT-LAB-V1\n")
        signed=CONTRACT["signature"]["message"]
        for required in ("u32_be_authenticated_security2_session",
                         "verified_transaction_transcript_sha256_32",
                         "fresh_client_challenge_32","u8_state_1"):
            self.assertIn(required,signed)

    def test_review_is_one_shot_and_must_be_local(self):
        requirements=CONTRACT["server_constraints"]
        for required in ("no_signature_before_physical_Review_OK",
                         "one_signature_per_completed_session_only",
                         "no_network_callback_can_trigger_local_review",
                         "completed_transcript_sha256_equals_requested_digest"):
            self.assertIn(required,requirements)
        self.assertIn("reject_malformed_der_wrong_device_wrong_digest_wrong_session_or_replay",
                      CONTRACT["client_constraints"])

    def test_not_a_production_enrollment_grant(self):
        permission=CONTRACT["authorization"]
        self.assertTrue(permission["laboratory_only"])
        self.assertTrue(all(not enabled for key,enabled in permission.items()
                            if key != "laboratory_only"))
        integration=ROOT/"custom_components/omote_manager"
        for file in integration.glob("*.py"):
            self.assertNotIn("omote-tx2-touch-receipt",file.read_text(),file.name)


if __name__=="__main__":
    unittest.main()
