"""Offline v2 mutually signed transaction -> v1-format signed receipt candidate.

This proves only that the receipt is cryptographically bound to a context
that BOTH software lab keys signed. It does not authenticate a live Security2
session or establish either approval or hardware-protected identity.
"""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import os
from pathlib import Path
import sys
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT=Path(__file__).resolve().parents[1] / "custom_components/omote_manager"


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/filename)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module


mutual=load("omote_mutual_context_v2_receipt_lab",
            "sec2_mutual_transaction_proof_v2_draft.py")
receipt=load("omote_mutual_context_v2_signed_receipt_lab",
             "enrollment_receipt_draft.py")


class SignedMutualTransactionReceiptOffline(unittest.TestCase):
    def setUp(self):
        self.ha=ec.generate_private_key(ec.SECP256R1())
        self.device=ec.generate_private_key(ec.SECP256R1())
        self.ha_pub=self.ha.public_key().public_bytes(
            Encoding.X962,PublicFormat.UncompressedPoint)
        self.device_pub=self.device.public_key().public_bytes(
            Encoding.X962,PublicFormat.UncompressedPoint)
        self.context={
            "version":2,"session_id":910234,"epoch":5,
            "tx_id":os.urandom(16).hex(),"device_id":"a1"*8,
            "ha_public_sec1_hex":self.ha_pub.hex(),
            "device_public_sec1_hex":self.device_pub.hex(),
            "ha_nonce_hex":os.urandom(32).hex(),
            "device_challenge_hex":os.urandom(32).hex(),
        }
        payload=mutual.canonical_context(self.context)
        self.proof={
            "context":dict(self.context),
            "ha_signature_der_hex":self.ha.sign(
                mutual.HA_DOMAIN+payload,ec.ECDSA(hashes.SHA256())).hex(),
            "device_signature_der_hex":self.device.sign(
                mutual.DEVICE_DOMAIN+payload,ec.ECDSA(hashes.SHA256())).hex(),
        }
        self.binding=mutual.derive_bound(self.proof,observed=self.context)
        self.receipt_body={
            "version":receipt.VERSION,
            "tx_id":self.context["tx_id"],
            "device_id":self.context["device_id"],
            "epoch":self.context["epoch"],
            "ha_key_sha256":self.binding["ha_key_sha256"],
            "device_key_sha256":self.binding["device_key_sha256"],
            "session_transcript_sha256":self.binding["session_transcript_sha256"],
            "nonce":os.urandom(16).hex(),
            "signer":"ha",
            "phase":"prepare",
        }
        self.receipt=receipt.make_test_receipt(self.receipt_body,self.ha)

    def check_receipt(self,**overrides):
        expected=dict(
            verified_peer_public_sec1=self.ha_pub,
            expected_signer="ha",
            expected_session_sha256=self.binding["session_transcript_sha256"],
            expected_tx_id=self.context["tx_id"],
            expected_epoch=self.context["epoch"],
            expected_device_id=self.context["device_id"],
            expected_ha_fingerprint=sha256(self.ha_pub).hexdigest(),
            expected_device_fingerprint=sha256(self.device_pub).hexdigest(),
        )
        return receipt.verify_receipt(self.receipt,**dict(expected,**overrides))

    def test_v2_both_signers_bound_then_receipt_valid_but_not_paired(self):
        self.assertEqual(self.check_receipt(),self.receipt_body)
        state=receipt.reconcile_offline(
            [self.receipt],
            ha_public_sec1=self.ha_pub,device_public_sec1=self.device_pub,
            session_sha256=self.binding["session_transcript_sha256"],
            tx_id=self.context["tx_id"],epoch=self.context["epoch"],
            device_id=self.context["device_id"])
        self.assertFalse(state["paired"])
        self.assertFalse(state["authenticated_reconnect_enabled"])
        self.assertFalse(state["deployment_enabled"])

    def test_transaction_swapped_cannot_reuse_both_proofs_or_old_receipt(self):
        altered=dict(self.context,tx_id=os.urandom(16).hex())
        with self.assertRaises(mutual.MutualProofRejected):
            mutual.derive_bound(
                dict(self.proof,context=altered),observed=altered)
        with self.assertRaises(receipt.ReceiptRejected):
            self.check_receipt(expected_tx_id=altered["tx_id"])

    def test_wrong_session_or_identity_cannot_reconcile(self):
        altered=dict(self.context,session_id=self.context["session_id"]+1)
        with self.assertRaises(mutual.MutualProofRejected):
            mutual.derive_bound(self.proof,observed=altered)
        with self.assertRaises(receipt.ReceiptRejected):
            self.check_receipt(expected_session_sha256="0"*64)
        with self.assertRaises(receipt.ReceiptRejected):
            self.check_receipt(expected_device_fingerprint="0"*64)


if __name__=="__main__":
    unittest.main()
