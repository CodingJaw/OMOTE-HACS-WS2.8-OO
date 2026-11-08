"""OFFLINE signed touchscreen lab receipt verifier; NOT device enrollment.

Requires independently observed Security2 facts and BOTH verified v2
transaction signatures. This module has NO live endpoint, HA services,
persistent identity/trust, or configuration write capability.

ESP-IDF 5.3.2 Security2 uses a legacy AES-GCM nonce scheme unsuitable for
production key enrollment; the software LAB device key is not hardware trusted.
"""
from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from .sec2_mutual_transaction_proof_v2_draft import (
    MutualProofRejected, derive_bound,
)

DOMAIN = b"OMOTE-SEC2-TX2-TOUCH-RECEIPT-LAB-V1\n"


class TouchReceiptRejected(ValueError):
    """A rejected or replayed lab diagnostic is never pairing authority."""


class TouchReceiptLabVerifier:
    """Volatile local duplicate guard, not a persistent anti-replay journal."""

    def __init__(self):
        self._consumed: set[tuple[int, str, bytes]] = set()

    def verify(
        self, *, envelope: object, observed: object,
        authenticated_session_id: int, challenge: bytes, receipt: bytes,
    ) -> dict:
        if (type(authenticated_session_id) is not int or
                not 1 <= authenticated_session_id <= 0xFFFFFFFF or
                type(observed) is not dict or
                observed.get("session_id") != authenticated_session_id):
            raise TouchReceiptRejected("authenticated-session-mismatch")
        if (type(challenge) is not bytes or len(challenge) != 32 or
                not any(challenge)):
            raise TouchReceiptRejected("invalid-fresh-client-challenge")
        if (type(receipt) is not bytes or
                not 11 <= len(receipt) <= 83 or
                receipt[0] != 2 or receipt[1] != 1 or
                not 8 <= receipt[2] <= 80 or
                len(receipt) != 3 + receipt[2]):
            raise TouchReceiptRejected("invalid-signed-touch-receipt-frame")

        try:
            verified = derive_bound(envelope, observed=observed)
        except MutualProofRejected:
            raise TouchReceiptRejected("unverified-mutual-transaction") from None

        bound_digest = verified["session_transcript_sha256"]
        replay_key = (authenticated_session_id, bound_digest, challenge)
        if replay_key in self._consumed:
            raise TouchReceiptRejected("duplicate-local-receipt")

        message = (DOMAIN + bytes([2]) +
                   authenticated_session_id.to_bytes(4, "big") +
                   bytes.fromhex(bound_digest) + challenge + bytes([1]))
        signature = receipt[3:]
        try:
            r, s = utils.decode_dss_signature(signature)
            if utils.encode_dss_signature(r, s) != signature:
                raise ValueError("noncanonical-signature")
            device_key = ec.EllipticCurvePublicKey.from_encoded_point(
                ec.SECP256R1(),
                bytes.fromhex(observed["device_public_sec1_hex"]),
            )
            device_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        except (ValueError, TypeError, KeyError, InvalidSignature):
            raise TouchReceiptRejected("invalid-device-touch-signature") from None

        self._consumed.add(replay_key)
        return {
            "lab_touch_review_signature_verified": True,
            "session_transcript_sha256": bound_digest,
            "device_key_sha256": verified["device_key_sha256"],
            "laboratory_only": True,
            "paired": False,
            "trusted": False,
            "deployment_enabled": False,
            "ota_enabled": False,
        }
