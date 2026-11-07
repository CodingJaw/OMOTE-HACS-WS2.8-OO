"""Offline proof transcript contract and signed fixture tests (never pairs)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "custom_components/omote_manager/sec2_verified_proofs_transcript_draft.py"
FIXTURE = ROOT / "fixtures/sec2_verified_proofs_transcript_vectors_v1.json"
CONTRACT = ROOT / "fixtures/sec2_verified_proofs_transcript_contract_v1.json"
spec=importlib.util.spec_from_file_location("omote_sec2_proof_transcript_lab",SOURCE)
transcript=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=transcript
spec.loader.exec_module(transcript)


class VerifiedProofTranscriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vector=json.loads(FIXTURE.read_text())
        cls.contract=json.loads(CONTRACT.read_text())
        cls.input=cls.vector["input"]
        cls.expected=cls.vector["expected"]

    def test_real_p256_signatures_match_pinned_binary_and_digest(self):
        self.assertEqual(transcript.derive(self.input),self.expected)
        self.assertEqual(bytes.fromhex(self.expected["canonical_payload_hex"])
                         .startswith(transcript.DOMAIN),True)

    def test_existing_proof_domains_and_no_permission(self):
        self.assertEqual(self.contract["inputs"],list(self.input))
        self.assertEqual(self.contract["transcript_domain"].encode("ascii"),
                         transcript.DOMAIN)
        self.assertEqual(self.contract["existing_ha_proof_domain"].encode("ascii"),
                         transcript.HA_DOMAIN)
        self.assertEqual(self.contract["existing_device_proof_domain"].encode("ascii"),
                         transcript.DEVICE_DOMAIN)
        self.assertTrue(self.contract["authorization"]["laboratory_only"])
        self.assertTrue(all(v is False for k,v in self.contract["authorization"].items()
                            if k!="laboratory_only"))
        self.assertFalse(transcript.production_pairing_enabled())
        self.assertFalse(transcript.device_write_enabled())

    def test_mutated_signed_proof_material_rejected(self):
        for field in ("session_id","ha_public_sec1_hex",
                      "device_public_sec1_hex","ha_nonce_hex",
                      "device_challenge_hex","ha_proof_signature_der_hex",
                      "device_proof_signature_der_hex"):
            value=self.input[field]
            tampered=dict(self.input)
            if field=="session_id":
                tampered[field]=value+1
            else:
                tampered[field]=value[:-1]+("a" if value[-1]!="a" else "b")
            with self.subTest(field=field),self.assertRaises(transcript.TranscriptRejected):
                transcript.derive(tampered)

    def test_transaction_and_epoch_alter_digest_but_never_grant_trust(self):
        for field,new_value in (("epoch",3),
                               ("tx_id","2"*32),
                               ("device_id","b"*16)):
            altered=dict(self.input,**{field:new_value})
            with self.subTest(field=field):
                changed=transcript.derive(altered)
                self.assertNotEqual(changed["transcript_sha256"],
                                    self.expected["transcript_sha256"])
                self.assertNotIn("paired",changed)
                self.assertNotIn("deployment_enabled",changed)

    def test_bad_types_lengths_and_extra_fields_fail_closed(self):
        variants=[None,{},dict(self.input,version=2),dict(self.input,epoch=0),
                  dict(self.input,session_id=True),dict(self.input,epoch=2**32),
                  dict(self.input,tx_id="AA"*16),
                  dict(self.input,ha_nonce_hex="a"*62),
                  dict(self.input,ha_proof_signature_der_hex="f"*200),
                  dict(self.input,unexpected=1)]
        for bad in variants:
            with self.subTest(case=str(bad)[:40]),self.assertRaises(transcript.TranscriptRejected):
                transcript.derive(bad)

    def test_no_runtime_registration_or_private_key_fixtures(self):
        file_text=SOURCE.read_text()
        fixture_text=FIXTURE.read_text()
        for forbidden in ("private_key", "nvs_set_blob(", "async_register(",
                          "httpd_register_uri_handler(", "efuse_write("):
            self.assertNotIn(forbidden,fixture_text)
            if forbidden!="private_key":
                self.assertNotIn(forbidden,file_text)
        self.assertEqual(self.vector["authorization"]["paired"],False)


if __name__=="__main__":
    unittest.main()
