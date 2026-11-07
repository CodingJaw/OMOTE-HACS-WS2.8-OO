"""OFFLINE v2 mutual proof of a complete Security2 enrollment transaction.

Both participants sign the SAME canonical context, with different role domains.
The caller MUST supply independently observed, authenticated local session
facts; this helper does not establish Security2 authenticity or grant pairing.
Never register or call from a production endpoint without a separate review.
"""
from __future__ import annotations

import re
from hashlib import sha256

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

VERSION = 2
HA_DOMAIN = b"OMOTE-SEC2-TX-PROOF-HA-V2\n"
DEVICE_DOMAIN = b"OMOTE-SEC2-TX-PROOF-DEVICE-V2\n"
DIGEST_DOMAIN = b"OMOTE-SEC2-TX-TRANSCRIPT-V2\n"
CONTEXT_FIELDS = frozenset((
    "version", "session_id", "epoch", "tx_id", "device_id",
    "ha_public_sec1_hex", "device_public_sec1_hex",
    "ha_nonce_hex", "device_challenge_hex",
))
ENVELOPE_FIELDS = frozenset((
    "context", "ha_signature_der_hex", "device_signature_der_hex",
))


class MutualProofRejected(ValueError):
    """Do not expose untrusted protocol input as authorization."""


def _u32(value: object) -> bytes:
    if type(value) is not int or not (1 <= value <= 0xFFFFFFFF):
        raise MutualProofRejected("invalid-u32")
    return value.to_bytes(4, "big")


def _hex(value: object, field: str, low: int, high: int) -> bytes:
    if (type(value) is not str or len(value) % 2 or
            re.fullmatch(r"[0-9a-f]*", value) is None):
        raise MutualProofRejected("invalid-" + field)
    length = len(value) // 2
    if not (low <= length <= high):
        raise MutualProofRejected("invalid-" + field)
    return bytes.fromhex(value)


def _point(value: object, field: str) -> bytes:
    point = _hex(value, field, 65, 65)
    if point[0] != 4:
        raise MutualProofRejected("invalid-" + field)
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except ValueError:
        raise MutualProofRejected("invalid-" + field) from None
    return point


def canonical_context(context: object) -> bytes:
    if type(context) is not dict or context.keys() != CONTEXT_FIELDS:
        raise MutualProofRejected("context-fields")
    if type(context["version"]) is not int or context["version"] != VERSION:
        raise MutualProofRejected("context-version")
    session = _u32(context["session_id"])
    epoch = _u32(context["epoch"])
    tx = _hex(context["tx_id"], "tx", 16, 16)
    dev = _hex(context["device_id"], "device-id", 8, 32)
    ha = _point(context["ha_public_sec1_hex"], "ha-public")
    device = _point(context["device_public_sec1_hex"], "device-public")
    hn = _hex(context["ha_nonce_hex"], "ha-nonce", 32, 32)
    dn = _hex(context["device_challenge_hex"], "device-challenge", 32, 32)
    return (bytes([VERSION]) + session + epoch + tx +
            bytes([len(dev)]) + dev + ha + device + hn + dn)


def _signature(hex_text: object, field: str) -> bytes:
    value = _hex(hex_text, field, 8, 80)
    try:
        r, s = utils.decode_dss_signature(value)
        if utils.encode_dss_signature(r, s) != value:
            raise MutualProofRejected("noncanonical-" + field)
    except ValueError:
        raise MutualProofRejected("invalid-" + field) from None
    return value


def derive_bound(envelope: object, *, observed: object) -> dict:
    """Require two verified signatures AND independently observed context.

    The caller is responsible for obtaining observed from a locally verified
    Security2 session, never from the envelope or untrusted JSON. This module
    is offline-only and cannot attest that the caller met that obligation.
    """
    if type(envelope) is not dict or envelope.keys() != ENVELOPE_FIELDS:
        raise MutualProofRejected("envelope-fields")
    declared = envelope["context"]
    claimed_bytes = canonical_context(declared)
    observed_bytes = canonical_context(observed)
    if claimed_bytes != observed_bytes:
        raise MutualProofRejected("observed-context-mismatch")
    ha_signature = _signature(envelope["ha_signature_der_hex"], "ha-signature")
    device_signature = _signature(
        envelope["device_signature_der_hex"], "device-signature")
    ha = bytes.fromhex(declared["ha_public_sec1_hex"])
    dev = bytes.fromhex(declared["device_public_sec1_hex"])
    ha_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ha)
    dev_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), dev)
    try:
        ha_key.verify(ha_signature, HA_DOMAIN + claimed_bytes,
                      ec.ECDSA(hashes.SHA256()))
        dev_key.verify(device_signature, DEVICE_DOMAIN + claimed_bytes,
                       ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        raise MutualProofRejected("invalid-mutual-proof-signature") from None
    transcript = (DIGEST_DOMAIN + claimed_bytes +
                  bytes([len(ha_signature)]) + ha_signature +
                  bytes([len(device_signature)]) + device_signature)
    return {
        "session_transcript_sha256": sha256(transcript).hexdigest(),
        "ha_key_sha256": sha256(ha).hexdigest(),
        "device_key_sha256": sha256(dev).hexdigest(),
        "canonical_transcript_hex": transcript.hex(),
        "paired": False,
        "trusted": False,
        "deployment_enabled": False,
        "ota_enabled": False,
    }


def production_pairing_enabled() -> bool:
    return False


def device_write_enabled() -> bool:
    return False
