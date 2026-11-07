"""OFFLINE-ONLY signed enrollment receipt verifier and reconciliation model.

Never registered in Home Assistant. Signature verification proves key possession
relative to public keys supplied by an already authenticated channel, NOT
hardware identity or durable authorization. In particular no output here is
suitable for granting pairing, reconnection or firmware write access.
"""
from __future__ import annotations

import json
import re
from hashlib import sha256

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

VERSION = "omote-enrollment-receipt-v1-draft"
DOMAIN = b"OMOTE-ENROLLMENT-RECEIPT-V1\n"
BODY_FIELDS = frozenset({"version", "tx_id", "device_id", "epoch",
                         "ha_key_sha256", "device_key_sha256",
                         "session_transcript_sha256", "nonce", "signer", "phase"})
PHASES = frozenset({"prepare", "commit_intent", "peer_confirmed"})
SIGNERS = frozenset({"ha", "device"})


class ReceiptRejected(ValueError):
    """Never return secrets or untrusted remote error text."""


def _hex(value: object, length: int) -> bool:
    return type(value) is str and bool(re.fullmatch(
        rf"[0-9a-f]{{{length}}}", value
    ))


def validate_body(body: object) -> dict:
    if type(body) is not dict or body.keys() != BODY_FIELDS:
        raise ReceiptRejected("receipt-fields")
    if body["version"] != VERSION:
        raise ReceiptRejected("receipt-version")
    if not _hex(body["tx_id"], 32) or not _hex(body["nonce"], 32):
        raise ReceiptRejected("receipt-nonce-or-transaction")
    if (type(body["device_id"]) is not str
            or not re.fullmatch(r"[0-9a-f]{16,64}", body["device_id"])
            or len(body["device_id"]) % 2):
        raise ReceiptRejected("receipt-device-id")
    for key in ("ha_key_sha256", "device_key_sha256", "session_transcript_sha256"):
        if not _hex(body[key], 64):
            raise ReceiptRejected("receipt-digest")
    if type(body["epoch"]) is not int or body["epoch"] < 1 or body["epoch"] > 0xFFFFFFFF:
        raise ReceiptRejected("receipt-epoch")
    if body["signer"] not in SIGNERS or type(body["signer"]) is not str:
        raise ReceiptRejected("receipt-signer")
    if body["phase"] not in PHASES or type(body["phase"]) is not str:
        raise ReceiptRejected("receipt-phase")
    return dict(body)


def signed_bytes(body: object) -> bytes:
    doc = validate_body(body)
    return DOMAIN + json.dumps(doc, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False).encode("ascii")


def _public_key(public_sec1: bytes):
    if type(public_sec1) is not bytes or len(public_sec1) != 65 or public_sec1[0] != 4:
        raise ReceiptRejected("invalid-public-key-encoding")
    try:
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_sec1)
        if key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint) != public_sec1:
            raise ReceiptRejected("noncanonical-public-key")
        return key
    except ValueError:
        raise ReceiptRejected("invalid-public-key") from None


def make_test_receipt(body: dict, signer_private_key) -> dict:
    """ONLY for isolated tests; must not be imported by runtime HA endpoints."""
    if not isinstance(signer_private_key, ec.EllipticCurvePrivateKey) or not isinstance(
            signer_private_key.curve, ec.SECP256R1):
        raise ReceiptRejected("wrong-test-key-type")
    signature = signer_private_key.sign(signed_bytes(body), ec.ECDSA(
        __import__("cryptography.hazmat.primitives.hashes",
                   fromlist=["SHA256"]).SHA256()
    ))
    return {"body": validate_body(body), "signature_der_hex": signature.hex()}


def verify_receipt(envelope: object, *, verified_peer_public_sec1: bytes,
                   expected_signer: str, expected_session_sha256: str,
                   expected_tx_id: str, expected_epoch: int,
                   expected_ha_fingerprint: str,
                   expected_device_fingerprint: str) -> dict:
    """Verify signed public metadata against independent, externally bound facts.

    The public key MUST originate from the already-verified encrypted
    channel, never from the untrusted receipt itself. This function is
    diagnostic only: even a valid signature cannot enroll the device.
    """
    if type(envelope) is not dict or set(envelope) != {"body", "signature_der_hex"}:
        raise ReceiptRejected("receipt-envelope")
    body = validate_body(envelope["body"])
    if not _hex(envelope["signature_der_hex"], len(envelope["signature_der_hex"])) or not (
            16 <= len(envelope["signature_der_hex"]) <= 160
            and len(envelope["signature_der_hex"]) % 2 == 0):
        raise ReceiptRejected("receipt-signature-format")
    if (expected_signer not in SIGNERS
            or body["signer"] != expected_signer
            or body["tx_id"] != expected_tx_id
            or body["epoch"] != expected_epoch
            or body["session_transcript_sha256"] != expected_session_sha256
            or body["ha_key_sha256"] != expected_ha_fingerprint
            or body["device_key_sha256"] != expected_device_fingerprint):
        raise ReceiptRejected("receipt-context-mismatch")
    key = _public_key(verified_peer_public_sec1)
    signed_fingerprint = sha256(verified_peer_public_sec1).hexdigest()
    required = (expected_ha_fingerprint if expected_signer == "ha"
                else expected_device_fingerprint)
    if signed_fingerprint != required:
        raise ReceiptRejected("peer-public-key-mismatch")
    try:
        key.verify(bytes.fromhex(envelope["signature_der_hex"]),
                   signed_bytes(body), ec.ECDSA(
                       __import__("cryptography.hazmat.primitives.hashes",
                                  fromlist=["SHA256"]).SHA256()
                   ))
    except (InvalidSignature, ValueError):
        raise ReceiptRejected("invalid-peer-signature") from None
    return body


def reconcile_offline(envelopes: list, *, ha_public_sec1: bytes,
                      device_public_sec1: bytes,
                      session_sha256: str, tx_id: str, epoch: int) -> dict:
    """Require six signed phases across both sides before diagnostic agreement.

    All outcomes have `paired=false`, including complete agreement.
    Missing receipts remain pending and MAY NOT be trusted automatically.
    """
    if type(envelopes) is not list or len(envelopes) > 12 or not _hex(session_sha256, 64):
        raise ReceiptRejected("invalid-reconciliation-input")
    ha_fp = sha256(ha_public_sec1).hexdigest()
    device_fp = sha256(device_public_sec1).hexdigest()
    seen = set()
    phases = set()
    for envelope in envelopes:
        if type(envelope) is not dict or type(envelope.get("body")) is not dict:
            raise ReceiptRejected("invalid-reconciliation-envelope")
        role = envelope["body"].get("signer")
        key = ha_public_sec1 if role == "ha" else device_public_sec1
        body = verify_receipt(
            envelope, verified_peer_public_sec1=key, expected_signer=role,
            expected_session_sha256=session_sha256, expected_tx_id=tx_id,
            expected_epoch=epoch, expected_ha_fingerprint=ha_fp,
            expected_device_fingerprint=device_fp,
        )
        identity = (body["signer"], body["phase"])
        nonce_key = (body["signer"], body["nonce"])
        if identity in phases or nonce_key in seen:
            raise ReceiptRejected("replayed-receipt")
        phases.add(identity)
        seen.add(nonce_key)
    expected = {(role, phase) for role in SIGNERS for phase in PHASES}
    return {"diagnostic": ("two_party_receipts_complete" if phases == expected
                           else "needs_authenticated_reconciliation"),
            "receipts_verified": len(phases),
            "paired": False, "trusted": False,
            "deployment_enabled": False, "ota_enabled": False,
            "authenticated_reconnect_enabled": False}
