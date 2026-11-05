"""Read-only firmware/HACS wire contract for LAB software device identity.

No HA trust enrollment, device-key pinning or configuration writes.
"""
import json
import os
from pathlib import Path
import unittest

FIXTURE = Path(__file__).with_name("fixtures") / "sec2_lab_device_identity_contract.json"


class DeviceIdentityLabContractTests(unittest.TestCase):
    def test_firmware_owned_contract_is_identical(self):
        local = json.loads(FIXTURE.read_text())
        upstream = os.environ.get("OMOTE_FIRMWARE_LAB_DEVICE_CONTRACT")
        if upstream:
            self.assertEqual(local, json.loads(Path(upstream).read_text()))

    def test_lab_key_is_not_claimed_hardware_trusted(self):
        spec = json.loads(FIXTURE.read_text())
        self.assertEqual(spec["contract"], "omote-sec2-lab-device-software-identity-v1")
        self.assertEqual(spec["transport"]["endpoint"], "omote-device-proof")
        self.assertTrue(spec["transport"]["requires_verified_encrypted_session"])
        self.assertEqual(spec["request"]["bytes"], 33)
        self.assertEqual(spec["response"]["header_bytes"], 68)
        self.assertEqual(spec["response"]["domain"],
                         "OMOTE-SEC2-LAB-DEVICE-PROOF-V1")
        self.assertFalse(spec["persistence"]["nvs_encryption_guaranteed"])
        self.assertFalse(spec["persistence"]["hardware_protected"])
        self.assertEqual(spec["persistence"]["on_invalid_record"],
                         "fail_closed_no_network_rotation")
        self.assertTrue(all(value is False for value in spec["authorization"].values()))

    def test_hacs_runtime_still_has_no_trust_or_device_proof_call(self):
        root = Path(__file__).resolve().parents[1] / "custom_components/omote_manager"
        api = (root / "api.py").read_text()
        pairing = (root / "pairing_model.py").read_text()
        self.assertNotIn("omote-device-proof", api)
        self.assertIn('"pairing_enabled": False', pairing)
        self.assertIn('"deployment_enabled": False', pairing)


if __name__ == "__main__":
    unittest.main()
