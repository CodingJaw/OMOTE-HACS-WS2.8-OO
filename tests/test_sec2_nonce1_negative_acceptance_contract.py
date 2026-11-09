"""Offline HACS compatibility contract for Security2 patch-1 negative tests.

No HA API, session, device connection, trust writes, OTA or deployment.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=json.loads((ROOT/"tests/fixtures/sec2_nonce1_negative_acceptance_contract.json").read_text())


class Security2NegativeAcceptanceContractTests(unittest.TestCase):
    def test_nonce_and_window_requirements(self):
        self.assertEqual(CONTRACT["contract"],
                         "omote-security2-nonce1-negative-acceptance-v1")
        transport=CONTRACT["transport"]
        self.assertEqual(transport["required_security2_patch"],1)
        self.assertEqual(transport["transaction_timeout_ms"],30000)
        self.assertEqual(transport["touch_review_timeout_ms"],60000)
        self.assertEqual(transport["lab_window_timeout_ms"],120000)
        self.assertTrue(transport["remote_version_advertisement_is_unauthenticated"])

    def test_hardware_negative_acceptance_remains_required(self):
        hardware=CONTRACT["hardware_required_before_production"]
        for item in (
            "verify_reject_without_signature_on_physical_device",
            "verify_expired_window_fails_closed_before_srp",
            "verify_real_reconnect_uses_new_srp_key_and_nonce",
            "verify_downgrade_never_silently_falls_back_to_patch0",
            "verify_firmware_rollback_and_NVS_configuration_retention",
        ):
            self.assertIn(item,hardware)

    def test_no_hacs_pairing_or_deployment_authority(self):
        auth=CONTRACT["authorization"]
        self.assertTrue(auth["laboratory_only"])
        self.assertTrue(all(v is False for k,v in auth.items()
                            if k!="laboratory_only"))
        self.assertTrue(all(CONTRACT["environment_isolation"].values()))
        integration=ROOT/"custom_components/omote_manager"
        for path in integration.glob("*.py"):
            self.assertNotIn("omote-security2-nonce1-negative-acceptance-v1",
                             path.read_text(),path.name)


if __name__=="__main__":
    unittest.main()
