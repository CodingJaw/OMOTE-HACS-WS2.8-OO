"""Offline signed local-touch receipt crypto tests; never contact OMOTE."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from hashlib import sha256
from types import ModuleType
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

HERE=Path(__file__).resolve().parents[1]/"custom_components/omote_manager"
PACKAGE="omote_offline_touch_receipt_tests"
pkg=ModuleType(PACKAGE)
pkg.__path__=[str(HERE)]
sys.modules.setdefault(PACKAGE,pkg)
spec=importlib.util.spec_from_file_location(
    PACKAGE+".sec2_tx_v2_signed_touch_receipt_lab_draft",
    HERE/"sec2_tx_v2_signed_touch_receipt_lab_draft.py")
lab=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=lab
spec.loader.exec_module(lab)
from importlib import import_module
proof=import_module(PACKAGE+".sec2_mutual_transaction_proof_v2_draft")


class SignedTouchLabDraftVerifierTests(unittest.TestCase):
    def setUp(self):
        self.ha=ec.generate_private_key(ec.SECP256R1())
        self.device=ec.generate_private_key(ec.SECP256R1())
        pub=lambda key:key.public_key().public_bytes(
            Encoding.X962,PublicFormat.UncompressedPoint)
        self.ha_pub=pub(self.ha)
        self.device_pub=pub(self.device)
        self.session=123456
        self.context={
            "version":2,"session_id":self.session,"epoch":1,
            "tx_id":os.urandom(16).hex(),
            "device_id":sha256(self.device_pub).digest()[:8].hex(),
            "ha_public_sec1_hex":self.ha_pub.hex(),
            "device_public_sec1_hex":self.device_pub.hex(),
            "ha_nonce_hex":os.urandom(32).hex(),
            "device_challenge_hex":os.urandom(32).hex(),
        }
        canonical=proof.canonical_context(self.context)
        self.envelope={
            "context":dict(self.context),
            "ha_signature_der_hex":self.ha.sign(
                proof.HA_DOMAIN+canonical,
                ec.ECDSA(hashes.SHA256())).hex(),
            "device_signature_der_hex":self.device.sign(
                proof.DEVICE_DOMAIN+canonical,
                ec.ECDSA(hashes.SHA256())).hex(),
        }
        self.digest=bytes.fromhex(
            proof.derive_bound(self.envelope,observed=self.context)
            ["session_transcript_sha256"])
        self.challenge=os.urandom(32)
        self.verifier=lab.TouchReceiptLabVerifier()

    def receipt(self, *, key=None, challenge=None, digest=None,
                session=None, domain=None, state=1):
        key=self.device if key is None else key
        challenge=self.challenge if challenge is None else challenge
        digest=self.digest if digest is None else digest
        session=self.session if session is None else session
        domain=lab.DOMAIN if domain is None else domain
        data=(domain+bytes([2])+session.to_bytes(4,"big")+
              digest+challenge+bytes([state]))
        sig=key.sign(data,ec.ECDSA(hashes.SHA256()))
        return bytes([2,1,len(sig)])+sig

    def verify(self, receipt=None, **overrides):
        args={
            "envelope":self.envelope,
            "observed":self.context,
            "authenticated_session_id":self.session,
            "challenge":self.challenge,
            "receipt":self.receipt() if receipt is None else receipt,
        }
        args.update(overrides)
        return self.verifier.verify(**args)

    def test_properly_signed_ack_only_reports_lab_flags(self):
        result=self.verify()
        self.assertTrue(result["lab_touch_review_signature_verified"])
        self.assertTrue(result["laboratory_only"])
        self.assertEqual(result["session_transcript_sha256"],self.digest.hex())
        for name in ("paired","trusted","deployment_enabled","ota_enabled"):
            self.assertFalse(result[name])

    def test_duplicate_response_rejected_by_volatile_guard(self):
        reply=self.receipt()
        self.verify(receipt=reply)
        with self.assertRaises(lab.TouchReceiptRejected):
            self.verify(receipt=reply)

    def test_unauthenticated_or_wrong_session_refused(self):
        for bad in (0,123457,True,None):
            with self.subTest(session=bad):
                with self.assertRaises(lab.TouchReceiptRejected):
                    self.verify(authenticated_session_id=bad)

    def test_mutual_signature_must_be_verified_first(self):
        tampered=dict(self.envelope,
                      ha_signature_der_hex="00"*70)
        with self.assertRaises(lab.TouchReceiptRejected):
            self.verify(envelope=tampered)
        modified=dict(self.context,epoch=2)
        with self.assertRaises(lab.TouchReceiptRejected):
            self.verify(observed=modified)

    def test_forged_device_signing_key_refused(self):
        rogue=ec.generate_private_key(ec.SECP256R1())
        with self.assertRaises(lab.TouchReceiptRejected):
            self.verify(receipt=self.receipt(key=rogue))

    def test_changed_digest_challenge_state_domain_refused(self):
        malformed=(
            self.receipt(digest=bytes(32)),
            self.receipt(challenge=bytes(32)),
            self.receipt(state=0),
            self.receipt(domain=b"OTHER-RECEIPT-DOMAIN"),
            self.receipt(session=self.session+1),
        )
        for wrong in malformed:
            with self.subTest(length=len(wrong)):
                with self.assertRaises(lab.TouchReceiptRejected):
                    self.verify(receipt=wrong)

    def test_malformed_response_frames_refused(self):
        good=self.receipt()
        damaged=bytearray(good)
        damaged[-1]^=1
        for bad in (b"", b"bad", good[:-1], good+b"x",
                    bytes([1])+good[1:],bytes([2,0])+good[2:],
                    bytes([2,2])+good[2:],
                    good[:2]+bytes([good[2]+1])+good[3:],
                    bytes(damaged), b"0"*120):
            with self.subTest(frame=str(bad)[:20]):
                with self.assertRaises(lab.TouchReceiptRejected):
                    self.verify(receipt=bad)

    def test_missing_or_zero_fresh_client_challenge_refused(self):
        for bad in (None,b"",bytes(32),b"1"*31,b"1"*33,True):
            with self.subTest(challenge=repr(bad)[:10]):
                with self.assertRaises(lab.TouchReceiptRejected):
                    self.verify(challenge=bad)

    def test_no_production_network_or_key_storage_registration(self):
        content=(HERE/"sec2_tx_v2_signed_touch_receipt_lab_draft.py").read_text()
        for forbidden in ("@websocket_api", "async_register(", "async_save(",
                          "Preferences", "nvs_set_blob(", "async_post(",
                          "device_write_enabled = True"):
            self.assertNotIn(forbidden,content)


if __name__=="__main__":
    unittest.main()
