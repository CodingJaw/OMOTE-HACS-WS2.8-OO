"""Offline integration: verified Security2 proofs -> signed receipt digest.

This is a local cryptographic model ONLY. No Home Assistant services,
hardware trust, eFuses or deployment are enabled by these tests.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import os
import sys
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parents[1] / "custom_components/omote_manager"


def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/filename)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module


proofs=load("omote_transcript_receipt_proofs_lab",
            "sec2_verified_proofs_transcript_draft.py")
receipts=load("omote_transcript_receipt_signatures_lab",
              "enrollment_receipt_draft.py")


class ProofToReceiptBindingOffline(unittest.TestCase):
    def setUp(self):
        self.ha=ec.generate_private_key(ec.SECP256R1())
        self.device=ec.generate_private_key(ec.SECP256R1())
        self.ha_pub=self.ha.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint)
        self.device_pub=self.device.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint)
        self.session_id=98316
        self.tx=os.urandom(16).hex()
        self.device_id="a1"*8
        self.ha_nonce=os.urandom(32)
        self.device_challenge=os.urandom(32)
        sid=self.session_id.to_bytes(4,"big")
        ha_sig=self.ha.sign(proofs.HA_DOMAIN+sid+self.ha_pub+self.ha_nonce,
                            ec.ECDSA(hashes.SHA256()))
        device_sig=self.device.sign(
            proofs.DEVICE_DOMAIN+sid+self.device_challenge+self.device_pub,
            ec.ECDSA(hashes.SHA256()))
        self.proof_data={
            "version":1, "session_id":self.session_id,"epoch":2,
            "tx_id":self.tx,"device_id":self.device_id,
            "ha_public_sec1_hex":self.ha_pub.hex(),
            "device_public_sec1_hex":self.device_pub.hex(),
            "ha_nonce_hex":self.ha_nonce.hex(),
            "device_challenge_hex":self.device_challenge.hex(),
            "ha_proof_signature_der_hex":ha_sig.hex(),
            "device_proof_signature_der_hex":device_sig.hex(),
        }
        self.derived=proofs.derive(self.proof_data)
        self.body={
            "version":receipts.VERSION, "tx_id":self.tx,
            "device_id":self.device_id,"epoch":2,
            "ha_key_sha256":self.derived["ha_key_sha256"],
            "device_key_sha256":self.derived["device_key_sha256"],
            "session_transcript_sha256":self.derived["transcript_sha256"],
            "nonce":os.urandom(16).hex(),"signer":"ha","phase":"prepare",
        }
        self.receipt=receipts.make_test_receipt(self.body,self.ha)

    def verify(self, **overrides):
        context=dict(
            verified_peer_public_sec1=self.ha_pub,expected_signer="ha",
            expected_session_sha256=self.derived["transcript_sha256"],
            expected_tx_id=self.tx,expected_device_id=self.device_id,
            expected_epoch=2,
            expected_ha_fingerprint=self.derived["ha_key_sha256"],
            expected_device_fingerprint=self.derived["device_key_sha256"],
        )
        return receipts.verify_receipt(self.receipt,**dict(context,**overrides))

    def test_verified_proofs_derive_receipt_bound_digest_without_trust(self):
        self.assertEqual(self.verify(),self.body)
        self.assertFalse(proofs.production_pairing_enabled())
        self.assertFalse(proofs.device_write_enabled())
        result=receipts.reconcile_offline(
            [self.receipt],ha_public_sec1=self.ha_pub,
            device_public_sec1=self.device_pub,
            session_sha256=self.derived["transcript_sha256"],
            tx_id=self.tx,epoch=2,device_id=self.device_id)
        self.assertFalse(result["paired"])
        self.assertFalse(result["deployment_enabled"])
        self.assertEqual(result["diagnostic"],"needs_authenticated_reconciliation")

    def test_independently_changed_transaction_digest_rejects_old_receipt(self):
        changed=proofs.derive(dict(self.proof_data,tx_id="f"*32))
        self.assertNotEqual(changed["transcript_sha256"],
                            self.derived["transcript_sha256"])
        with self.assertRaises(receipts.ReceiptRejected):
            self.verify(expected_session_sha256=changed["transcript_sha256"])

    def test_signed_proof_wrong_session_cannot_derive_receipt_context(self):
        with self.assertRaises(proofs.TranscriptRejected):
            proofs.derive(dict(self.proof_data,session_id=self.session_id+1))
        with self.assertRaises(receipts.ReceiptRejected):
            self.verify(expected_session_sha256="a"*64)


if __name__=="__main__":
    unittest.main()
