"""Read-only, authenticated v2 touchscreen-review LAB protocol parity checks.

The opt-in HACS diagnostic does not interpret Review OK as pairing.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WIRE = json.loads((ROOT / "tests/fixtures/sec2_tx_v2_local_review_lab_wire_contract.json").read_text())


class LocalReviewLabContractTests(unittest.TestCase):
    def test_exact_encrypted_read_only_review_framing(self):
        self.assertEqual(WIRE["transport"]["endpoint"], "omote-tx2-review")
        self.assertEqual(WIRE["transport"]["port"], 18082)
        self.assertEqual(WIRE["transport"]["security"],
                         "protocomm-security2-srp6a-aes256gcm")
        self.assertTrue(WIRE["transport"]["same_authenticated_session_required"])
        self.assertEqual(WIRE["request"], "u8_version_2|transcript_sha256_32")
        self.assertEqual(
            WIRE["response"],
            "u8_version_2|u8_state_0_pending_1_reviewed|transcript_sha256_32",
        )

    def test_no_trust_or_write_authorization(self):
        self.assertTrue(WIRE["authorization"]["laboratory_only"])
        self.assertTrue(all(
            value is False for key, value in WIRE["authorization"].items()
            if key != "laboratory_only"
        ))
        constraints = WIRE["constraints"]
        for required in (
            "session_must_equal_completed_proof_security2_callback_session",
            "review_snapshot_session_must_equal_same_security2_callback_session",
            "review_state_is_only_mutated_by_physical_touch_or_expiration",
            "reject_or_timeout_or_close_returns_no_reviewed_status",
        ):
            self.assertIn(required, constraints)

    def test_lab_only_not_registered_as_hacs_deploy_path(self):
        # Only the isolated transport and session may reference this endpoint.
        integration = ROOT / "custom_components/omote_manager"
        users = {path.name for path in integration.glob("*.py")
                 if 'omote-tx2-review' in path.read_text()}
        self.assertEqual(users, {"sec2_lab_http.py", "sec2_lab_session.py"})


if __name__ == "__main__":
    unittest.main()
