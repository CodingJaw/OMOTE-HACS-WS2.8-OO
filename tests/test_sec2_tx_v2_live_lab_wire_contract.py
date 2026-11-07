"""HACS must match firmware's opt-in Security2 v2 laboratory wire contract.

No Home Assistant component registers these endpoints or treats the
returned digest as enrollment authorization. The manual CLI tool in the
firmware repository is the only live experimental client.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
WIRE=json.loads((ROOT/"tests/fixtures/sec2_tx_v2_live_lab_wire_contract.json").read_text())


class Security2TxV2WireCompatibility(unittest.TestCase):
    def test_wire_layout_expected_encrypted_endpoints(self):
        self.assertEqual(WIRE["platformio_environment"],
                         "waveshare28v2_omote_sec2_tx_v2_lab")
        self.assertEqual(WIRE["transport"]["port"],18082)
        self.assertEqual(WIRE["endpoints"]["open"],"omote-tx2-open")
        self.assertEqual(WIRE["endpoints"]["commit"],"omote-tx2-commit")
        self.assertIn("ha_public_sec1_65",WIRE["open"]["request"])
        self.assertIn("tx_id_random_16",WIRE["open"]["response"])
        self.assertIn("transcript_sha256_32",WIRE["commit"]["response"])

    def test_no_trust_write_or_deployment_permissions(self):
        self.assertTrue(WIRE["authorization"]["laboratory_only"])
        self.assertFalse(any(
            v for k,v in WIRE["authorization"].items() if k!="laboratory_only"))
        self.assertIn("session_id_taken_only_from_decrypted_protocomm_callback",
                      WIRE["constraints"])
        self.assertIn("client_verifies_device_signature_and_digest_independently",
                      WIRE["constraints"])

    def test_no_live_hacs_registration_for_draft(self):
        src=(ROOT/"custom_components/omote_manager/sec2_mutual_transaction_proof_v2_draft.py").read_text()
        for banned in ("@websocket_api", "async_register(",
                       "async_save(", "requests.post("):
            self.assertNotIn(banned,src)


if __name__=="__main__":
    unittest.main()
