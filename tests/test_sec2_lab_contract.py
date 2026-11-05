"""Shared encrypted LAB key-proof contract; never grant HA pairing access.

This is a protocol-compatibility regression, not a working HACS pairing
client. The existing dev20 integration remains read-only and connected.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

FIXTURE = Path(__file__).with_name("fixtures") / "sec2_lab_ha_proof_contract.json"


class LabProofContractTests(unittest.TestCase):
    def test_firmware_owned_contract_is_pinned(self):
        local = json.loads(FIXTURE.read_text())
        upstream = os.environ.get("OMOTE_FIRMWARE_LAB_PROOF_CONTRACT")
        if upstream:
            self.assertEqual(local, json.loads(Path(upstream).read_text()))

    def test_every_wire_field_is_strict_and_unprivileged(self):
        model = json.loads(FIXTURE.read_text())
        self.assertEqual(model["contract"], "omote-sec2-lab-ha-candidate-proof-v1")
        self.assertEqual(model["transport"]["endpoint"], "omote-ha-proof")
        self.assertTrue(model["transport"]["must_be_inside_completed_encrypted_security2_session"])
        self.assertEqual(model["request"]["header_bytes"], 100)
        self.assertEqual(model["request"]["version"], 1)
        self.assertEqual(model["request"]["domain"], "OMOTE-SEC2-LAB-HA-PROOF-V1")
        self.assertEqual(model["response"]["authenticated_encrypted_payload_ascii"],
                         "OMOTE-LAB-HA-PROOF-OK-V1")
        self.assertTrue(all(value is False for value in model["authorization"].values()))

    def test_no_hacs_runtime_pairing_or_remote_writes_enabled(self):
        root = Path(__file__).resolve().parents[1] / "custom_components/omote_manager"
        api = (root / "api.py").read_text()
        pairing = (root / "pairing_model.py").read_text()
        self.assertNotIn("omote-ha-proof", api)
        self.assertIn('"pairing_enabled": False', pairing)
        self.assertIn('"deployment_enabled": False', pairing)


if __name__ == "__main__":
    unittest.main()
