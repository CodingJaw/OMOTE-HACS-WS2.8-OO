"""Offline mutual Security2 transaction proof v2: no pairing, no live API."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

SOURCE = Path(__file__).resolve().parent / "../custom_components/omote_manager/sec2_mutual_transaction_proof_v2_draft.py"
CONTRACT = Path(__file__).resolve().parent / "fixtures/sec2_mutual_transaction_proof_v2_contract.json"
spec=importlib.util.spec_from_file_location("omote_sec2_mutual_v2_offline",SOURCE)
proof=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=proof
spec.loader.exec_module(proof)


class MutualSecurity2TransactionProofV2(unittest.TestCase):
    def setUp(self):
        self.ha_key=ec.generate_private_key(ec.SECP256R1())
        self.device_key=ec.generate_private_key(ec.SECP256R1())
        self.ha_pub=self.ha_key.public_key().public_bytes(
            Encoding.X962,PublicFormat.UncompressedPoint)
        self.device_pub=self.device_key.public_key().public_bytes(
            Encoding.X962,PublicFormat.UncompressedPoint)
        self.context={
            "version":2,"session_id":94123,"epoch":2,
            "tx_id":os.urandom(16).hex(),"device_id":"a1"*8,
            "ha_public_sec1_hex":self.ha_pub.hex(),
            "device_public_sec1_hex":self.device_pub.hex(),
            "ha_nonce_hex":os.urandom(32).hex(),
            "device_challenge_hex":os.urandom(32).hex(),
        }
        self.context_bytes=proof.canonical_context(self.context)
        self.envelope={
            "context":dict(self.context),
            "ha_signature_der_hex":self.ha_key.sign(
                proof.HA_DOMAIN+self.context_bytes,
                ec.ECDSA(hashes.SHA256())).hex(),
            "device_signature_der_hex":self.device_key.sign(
                proof.DEVICE_DOMAIN+self.context_bytes,
                ec.ECDSA(hashes.SHA256())).hex(),
        }

    def test_valid_both_signatures_still_never_authorize(self):
        result=proof.derive_bound(self.envelope,observed=self.context)
        self.assertEqual(len(result["session_transcript_sha256"]),64)
        self.assertEqual(result["ha_key_sha256"],
                         __import__("hashlib").sha256(self.ha_pub).hexdigest())
        self.assertEqual(result["device_key_sha256"],
                         __import__("hashlib").sha256(self.device_pub).hexdigest())
        for name in ("paired","trusted","deployment_enabled","ota_enabled"):
            self.assertIs(result[name],False)
        self.assertFalse(proof.production_pairing_enabled())
        self.assertFalse(proof.device_write_enabled())

    def test_both_proofs_sign_same_context_and_distinct_role_domains(self):
        self.assertNotEqual(proof.HA_DOMAIN,proof.DEVICE_DOMAIN)
        self.assertNotEqual(proof.DIGEST_DOMAIN,proof.HA_DOMAIN)
        self.assertNotEqual(proof.DIGEST_DOMAIN,proof.DEVICE_DOMAIN)
        changed=dict(self.context,epoch=3)
        self.assertNotEqual(proof.canonical_context(changed),self.context_bytes)
        swapped=dict(self.envelope,
                     ha_signature_der_hex=self.envelope["device_signature_der_hex"],
                     device_signature_der_hex=self.envelope["ha_signature_der_hex"])
        with self.assertRaises(proof.MutualProofRejected):
            proof.derive_bound(swapped,observed=self.context)

    def test_independent_observation_mismatch_fails_for_every_field(self):
        changes={
            "session_id":94124,"epoch":3,"tx_id":"b"*32,
            "device_id":"b1"*8,"ha_nonce_hex":"d"*64,
            "device_challenge_hex":"e"*64,
            "ha_public_sec1_hex":self.device_pub.hex(),
            "device_public_sec1_hex":self.ha_pub.hex(),
        }
        for field,value in changes.items():
            with self.subTest(field=field),self.assertRaises(proof.MutualProofRejected):
                proof.derive_bound(self.envelope,
                                   observed=dict(self.context,**{field:value}))

    def test_mutation_of_signatures_or_signed_context_refused(self):
        for field in ("ha_signature_der_hex","device_signature_der_hex"):
            original=self.envelope[field]
            bad=dict(self.envelope,**{field:original[:-2]+"00"})
            with self.subTest(field=field),self.assertRaises(proof.MutualProofRejected):
                proof.derive_bound(bad,observed=self.context)
        for field,new_value in (("epoch",3),("tx_id","d"*32),
                                ("device_id","c"*16),("session_id",888),
                                ("ha_nonce_hex","e"*64),
                                ("device_challenge_hex","c"*64)):
            altered=dict(self.context,**{field:new_value})
            bad=dict(self.envelope,context=altered)
            with self.subTest(field=field),self.assertRaises(proof.MutualProofRejected):
                # Even if the verifier is fooled into taking new expected
                # values, signatures still cannot be replayed across tx.
                proof.derive_bound(bad,observed=altered)

    def test_malformed_context_or_signature_fails_closed(self):
        bad_examples=(
            None,dict(self.context,version=True),
            dict(self.context,version=1),dict(self.context,session_id=0),
            dict(self.context,epoch=2**32),
            dict(self.context,tx_id="AA"*16),
            dict(self.context,device_id="a"*14),
            dict(self.context,ha_nonce_hex="00"),
            dict(self.context,unexpected=1),
        )
        for bad in bad_examples:
            with self.subTest(bad=str(bad)[:45]),self.assertRaises(proof.MutualProofRejected):
                proof.canonical_context(bad)
        for bad in (None,{},dict(self.envelope,unknown=1),
                    dict(self.envelope,ha_signature_der_hex=[]),
                    dict(self.envelope,device_signature_der_hex="00"*90)):
            with self.subTest(bad=str(type(bad))),self.assertRaises(proof.MutualProofRejected):
                proof.derive_bound(bad,observed=self.context)

    def test_envelope_cannot_substitute_its_own_observed_context(self):
        replay=dict(self.envelope,context=dict(self.context,session_id=9999))
        with self.assertRaises(proof.MutualProofRejected):
            proof.derive_bound(replay,observed=self.context)
        with self.assertRaises(proof.MutualProofRejected):
            proof.derive_bound(self.envelope,observed=None)

    def test_contract_requires_live_independent_state_and_disables_all_privileges(self):
        doc=json.loads(CONTRACT.read_text())
        self.assertEqual(doc["context_fields"],list(self.context))
        self.assertEqual(doc["version"],2)
        self.assertTrue(doc["authorization"]["laboratory_only"])
        self.assertTrue(all(not value for key,value in doc["authorization"].items()
                            if key!="laboratory_only"))
        self.assertIn("session_cookie_from_verified_encrypted_security2_local_channel",
                      doc["required_independent_observations"])

    def test_no_live_endpoints_or_secret_material_persisted(self):
        src=SOURCE.read_text()
        for token in ("httpd_register_uri_handler(", "nvs_set_blob(",
                      "efuse_write(", "async_register(", ".async_save(",
                      "WiFi.begin(", "ota_start("):
            self.assertNotIn(token,src)


if __name__=="__main__":
    unittest.main()
