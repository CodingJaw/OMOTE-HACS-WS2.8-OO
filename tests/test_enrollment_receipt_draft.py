"""Offline signed receipt and non-authorizing reconciliation tests."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom_components/omote_manager/enrollment_receipt_draft.py"
CONTRACT = ROOT / "tests/fixtures/enrollment_receipt_contract_v1.json"
spec = importlib.util.spec_from_file_location("omote_enrollment_receipt_offline", MODULE)
receipt = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = receipt
spec.loader.exec_module(receipt)


class SignedReceiptTests(unittest.TestCase):
    def setUp(self):
        self.ha = ec.generate_private_key(ec.SECP256R1())
        self.device = ec.generate_private_key(ec.SECP256R1())
        self.ha_pub = self.ha.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint)
        self.device_pub = self.device.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint)
        from hashlib import sha256
        self.ha_fp = sha256(self.ha_pub).hexdigest()
        self.device_fp = sha256(self.device_pub).hexdigest()
        self.context = {
            "expected_session_sha256": "a" * 64,
            "expected_tx_id": "1" * 32,
            "expected_device_id": "f" * 16,
            "expected_epoch": 2,
            "expected_ha_fingerprint": self.ha_fp,
            "expected_device_fingerprint": self.device_fp,
        }

    def body(self, signer="ha", phase="prepare", nonce="3"*32, **changes):
        body = {
            "version": receipt.VERSION, "tx_id": self.context["expected_tx_id"],
            "device_id": self.context["expected_device_id"],
            "epoch": self.context["expected_epoch"],
            "ha_key_sha256": self.ha_fp, "device_key_sha256": self.device_fp,
            "session_transcript_sha256": self.context["expected_session_sha256"],
            "nonce": nonce, "signer": signer, "phase": phase,
        }
        return dict(body, **changes)

    def signed(self, signer="ha", phase="prepare", nonce="3"*32, **changes):
        private = self.ha if signer == "ha" else self.device
        return receipt.make_test_receipt(self.body(signer, phase, nonce, **changes), private)

    def verify(self, envelope, signer="ha", key=None, **context):
        data = dict(self.context, **context)
        return receipt.verify_receipt(
            envelope, verified_peer_public_sec1=(key if key is not None
            else (self.ha_pub if signer == "ha" else self.device_pub)),
            expected_signer=signer, **data,
        )

    def test_shared_firmware_contract_and_forbidden_permissions(self):
        obj = json.loads(CONTRACT.read_text())
        path = os.getenv("OMOTE_FIRMWARE_ENROLLMENT_RECEIPT_CONTRACT")
        if path:
            self.assertEqual(obj, json.loads(Path(path).read_text()))
        self.assertEqual(obj["body_fields"], sorted(receipt.BODY_FIELDS)
                         if obj["body_fields"] == sorted(receipt.BODY_FIELDS)
                         else obj["body_fields"])
        self.assertEqual(set(obj["body_fields"]), receipt.BODY_FIELDS)
        self.assertTrue(obj["authorization"]["laboratory_only"])
        self.assertFalse(any(value for key, value in obj["authorization"].items()
                             if key != "laboratory_only"))

    def test_valid_signatures_both_roles_and_transcript(self):
        for signer in ("ha", "device"):
            with self.subTest(signer=signer):
                envelope = self.signed(signer=signer)
                self.assertEqual(self.verify(envelope, signer=signer)["signer"], signer)

    def test_forgery_wrong_public_key_tamper_and_session_mismatch_fail(self):
        envelope = self.signed()
        for key, value in (("phase", "peer_confirmed"),
                           ("device_id", "e"*16),
                           ("epoch", 1),
                           ("nonce", "4"*32)):
            tampered = {"body": dict(envelope["body"], **{key: value}),
                        "signature_der_hex": envelope["signature_der_hex"]}
            with self.subTest(tampered=key), self.assertRaises(receipt.ReceiptRejected):
                self.verify(tampered)
        with self.assertRaises(receipt.ReceiptRejected):
            self.verify(envelope, key=self.device_pub)
        with self.assertRaises(receipt.ReceiptRejected):
            self.verify(envelope, expected_session_sha256="b"*64)
        bad = dict(envelope, signature_der_hex="00"*70)
        with self.assertRaises(receipt.ReceiptRejected):
            self.verify(bad)

    def test_signed_but_wrong_context_still_rejected(self):
        signed_wrong = self.signed(ha_key_sha256="d"*64)
        with self.assertRaises(receipt.ReceiptRejected):
            self.verify(signed_wrong)
        signed_wrong_device = self.signed(device_id="e"*16)
        with self.assertRaises(receipt.ReceiptRejected):
            self.verify(signed_wrong_device)

    def test_malformed_fields_and_keys_fail_closed(self):
        envelope = self.signed()
        for bad in (None, {}, {"body": envelope["body"]},
                    {"body": envelope["body"], "signature_der_hex": None},
                    dict(envelope, signature_der_hex=[]),
                    dict(envelope, signature_der_hex="x"*80)):
            with self.subTest(bad=str(type(bad))), self.assertRaises(receipt.ReceiptRejected):
                self.verify(bad)
        for bad in (dict(self.body(), signer=[]), dict(self.body(), phase={}),
                    dict(self.body(), epoch=True)):
            with self.assertRaises(receipt.ReceiptRejected):
                receipt.validate_body(bad)

    def test_missing_peer_receipts_never_authorize(self):
        docs = [self.signed(signer="ha", phase="prepare")]
        result = receipt.reconcile_offline(
            docs, ha_public_sec1=self.ha_pub, device_public_sec1=self.device_pub,
            session_sha256=self.context["expected_session_sha256"],
            tx_id=self.context["expected_tx_id"],
            device_id=self.context["expected_device_id"], epoch=2,
        )
        self.assertEqual(result["diagnostic"], "needs_authenticated_reconciliation")
        self.assertFalse(result["paired"])
        self.assertFalse(result["deployment_enabled"])

    def test_six_signed_receipts_still_do_not_enroll(self):
        docs = []
        n = 1
        for phase in ("prepare", "commit_intent", "peer_confirmed"):
            for signer in ("ha", "device"):
                docs.append(self.signed(signer, phase, format(n, "032x")))
                n += 1
        result = receipt.reconcile_offline(
            docs, ha_public_sec1=self.ha_pub, device_public_sec1=self.device_pub,
            session_sha256=self.context["expected_session_sha256"],
            tx_id=self.context["expected_tx_id"],
            device_id=self.context["expected_device_id"], epoch=2,
        )
        self.assertEqual(result["diagnostic"], "two_party_receipts_complete")
        self.assertEqual(result["receipts_verified"], 6)
        self.assertFalse(result["paired"])
        self.assertFalse(result["authenticated_reconnect_enabled"])
        self.assertFalse(result["deployment_enabled"])

    def test_replayed_receipt_and_distinct_peer_context_fail(self):
        docs = [self.signed()]
        kw = dict(ha_public_sec1=self.ha_pub, device_public_sec1=self.device_pub,
                  session_sha256=self.context["expected_session_sha256"],
                  tx_id=self.context["expected_tx_id"],
                  device_id=self.context["expected_device_id"], epoch=2)
        with self.assertRaises(receipt.ReceiptRejected):
            receipt.reconcile_offline(docs + docs, **kw)
        with self.assertRaises(receipt.ReceiptRejected):
            receipt.reconcile_offline(docs, **dict(kw, tx_id="2"*32))
        with self.assertRaises(receipt.ReceiptRejected):
            receipt.reconcile_offline(docs, **dict(kw, epoch=3))

    def test_no_live_registration_storage_or_pairing(self):
        src = MODULE.read_text()
        for banned in ("@websocket_api", "async_register", ".async_save(",
                       "nvs_set_blob(", "efuse_write(", "post(", "put("):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
