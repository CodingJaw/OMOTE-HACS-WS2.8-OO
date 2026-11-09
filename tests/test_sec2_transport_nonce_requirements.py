"""HACS offline nonce-safety compatibility contract for future pairing.

No Home Assistant credential, network, trust or deployment actions.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=json.loads(
    (ROOT/"tests/fixtures/sec2_transport_nonce_requirements_v1.json").read_text()
)


class Security2TransportNonceRequirementsTests(unittest.TestCase):
    def test_legacy_nonce_must_not_be_used_for_production_pairing(self):
        requirement=CONTRACT["nonce_policy"]
        self.assertEqual(requirement["legacy_patch"],0)
        self.assertEqual(requirement["minimum_counter_patch"],1)
        for name in (
            "production_pairing_must_reject_legacy_patch",
            "require_client_counter_after_every_encryption_and_decryption",
            "require_firmware_counter_after_every_encryption_and_decryption",
            "require_cryptographically_authenticated_negotiated_patch",
            "require_bidirectional_unique_nonce_across_session",
            "require_safe_concurrent_counter_handling_and_overflow_rejection",
            "no_silent_downgrade",
            "counter_capability_alone_is_not_production_authorization",
        ):
            self.assertIs(requirement[name],True,name)

    def test_legacy_diagnostic_compatibility_is_explicit_not_trust(self):
        lab=CONTRACT["existing_lab"]
        self.assertTrue(
            lab["esp_idf_5_3_2_patch0_allowed_for_isolated_nonsecret_hardware_diagnostics"])
        self.assertTrue(lab["existing_security2_lab_must_remain_backward_compatible"])
        self.assertFalse(lab["live_ha_enrollment_enabled"])
        self.assertFalse(lab["device_configuration_write_enabled"])
        auth=CONTRACT["authorization"]
        self.assertTrue(auth["laboratory_only"])
        self.assertTrue(all(not v for k,v in auth.items() if k!="laboratory_only"))

    def test_source_anchors_and_no_registered_hacs_crypto_downgrade(self):
        src=CONTRACT["evidence"]
        for name in ("legacy_python","legacy_firmware","counter_python",
                     "counter_firmware"):
            self.assertTrue(src[name].startswith("https://github.com/espressif/esp-idf/blob/"))
        integration=ROOT/"custom_components/omote_manager"
        for path in integration.glob("*.py"):
            self.assertNotIn("sec2_transport_nonce_requirements_v1",path.read_text())


if __name__=="__main__":
    unittest.main()
