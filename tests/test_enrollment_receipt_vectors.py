"""Verify byte-for-byte pinned P256 C++/Python test vectors without live pairing."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"custom_components/omote_manager/enrollment_receipt_draft.py"
FIXTURE=ROOT/"tests/fixtures/enrollment_receipt_vectors_v1.json"
spec=importlib.util.spec_from_file_location("omote_signed_vectors_only",PATH)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)


class SignedInteroperabilityVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectors=json.loads(FIXTURE.read_text())["vectors"]

    def test_canonical_signature_and_independent_context(self):
        self.assertEqual(len(self.vectors),2)
        for item in self.vectors:
            b=item["body"]
            with self.subTest(signer=b["signer"]):
                payload=module.signed_bytes(b)
                self.assertEqual(payload.hex(),item["canonical_payload_hex"])
                pub=bytes.fromhex(item["public_key_sec1_hex"])
                verified=module.verify_receipt(
                    {"body":b,"signature_der_hex":item["signature_der_hex"]},
                    verified_peer_public_sec1=pub,expected_signer=b["signer"],
                    expected_session_sha256=b["session_transcript_sha256"],
                    expected_tx_id=b["tx_id"],expected_epoch=b["epoch"],
                    expected_device_id=b["device_id"],
                    expected_ha_fingerprint=b["ha_key_sha256"],
                    expected_device_fingerprint=b["device_key_sha256"])
                self.assertEqual(verified,b)

    def test_tampered_pinned_vector_rejected(self):
        for item in self.vectors:
            b=item["body"]
            bad=dict(b, phase="peer_confirmed" if b["phase"]!="peer_confirmed" else "prepare")
            with self.subTest(signer=b["signer"]),self.assertRaises(module.ReceiptRejected):
                module.verify_receipt(
                    {"body":bad,"signature_der_hex":item["signature_der_hex"]},
                    verified_peer_public_sec1=bytes.fromhex(item["public_key_sec1_hex"]),
                    expected_signer=b["signer"],
                    expected_session_sha256=b["session_transcript_sha256"],
                    expected_tx_id=b["tx_id"],expected_epoch=b["epoch"],
                    expected_device_id=b["device_id"],
                    expected_ha_fingerprint=b["ha_key_sha256"],
                    expected_device_fingerprint=b["device_key_sha256"])

    def test_no_private_key_in_shared_vectors(self):
        data=FIXTURE.read_text()
        self.assertNotIn("private_key",data)
        self.assertNotIn("pin",data.lower())
        for v in self.vectors:
            self.assertEqual(len(bytes.fromhex(v["public_key_sec1_hex"])),65)


if __name__=="__main__":
    unittest.main()
