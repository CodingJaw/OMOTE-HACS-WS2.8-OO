"""OFFLINE verified Security2 proof transcript draft; NOT a pairing authority.

This helper only operates on public, explicitly supplied proof messages. It
verifies both P-256 signatures with the *existing* Security2 LAB proof domains
and computes deterministic canonical bytes. A real caller must additionally
establish that the session_id is the locally authenticated Security2 cookie
and that both proofs were observed inside that exact encrypted session.
No trusted runtime calls this module; it cannot grant pairing or writes.
"""
from __future__ import annotations

import re
from hashlib import sha256

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

VERSION = 1
DOMAIN = b"OMOTE-SEC2-VERIFIED-PROOFS-V1\n"
HA_DOMAIN = b"OMOTE-SEC2-LAB-HA-PROOF-V1"
DEVICE_DOMAIN = b"OMOTE-SEC2-LAB-DEVICE-PROOF-V1"
FIELDS = frozenset((
    "version", "session_id", "epoch", "tx_id", "device_id",
    "ha_public_sec1_hex", "device_public_sec1_hex", "ha_nonce_hex",
    "device_challenge_hex", "ha_proof_signature_der_hex",
    "device_proof_signature_der_hex",
))


class TranscriptRejected(ValueError):
    """Fail closed without treating untrusted data as an authenticated peer."""


def _u32(value: object) -> bytes:
    if type(value) is not int or not 1 <= value <= 0xFFFFFFFF:
        raise TranscriptRejected("invalid-session-id-or-epoch")
    return value.to_bytes(4, "big")


def _hex(value: object, name: str, *, exact_bytes: int | None = None,
         minimum_bytes: int = 0, maximum_bytes: int = 255) -> bytes:
    if (type(value) is not str or len(value) % 2 or
            re.fullmatch(r"[0-9a-f]*", value) is None):
        raise TranscriptRejected("invalid-" + name)
    if exact_bytes is not None and len(value) != exact_bytes * 2:
        raise TranscriptRejected("invalid-" + name)
    data = bytes.fromhex(value)
    if not minimum_bytes <= len(data) <= maximum_bytes:
        raise TranscriptRejected("invalid-" + name)
    return data


def _public_point(value: object, name: str):
    raw = _hex(value, name, exact_bytes=65)
    if raw[0] != 4:
        raise TranscriptRejected("invalid-" + name)
    try:
        key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), raw)
    except ValueError:
        raise TranscriptRejected("invalid-" + name) from None
    return raw, key


def derive(data: object) -> dict:
    """Verify both public key possession proofs and derive transcript digest.

    SECURITY BOUNDARY: signature verification alone cannot establish that
    session_id, nonce/challenge or key material actually originated from a
    locally authenticated Security2 session. It is NOT permission to enroll.
    """
    if type(data) is not dict or data.keys() != FIELDS:
        raise TranscriptRejected("unexpected-fields")
    if type(data["version"]) is not int or data["version"] != VERSION:
        raise TranscriptRejected("version")
    sid = _u32(data["session_id"])
    epoch = _u32(data["epoch"])
    tx = _hex(data["tx_id"], "tx-id", exact_bytes=16)
    did = _hex(data["device_id"], "device-id",
               minimum_bytes=8, maximum_bytes=32)
    ha_pub, ha_key = _public_point(data["ha_public_sec1_hex"], "ha-key")
    device_pub, device_key = _public_point(
        data["device_public_sec1_hex"], "device-key")
    hn = _hex(data["ha_nonce_hex"], "ha-nonce", exact_bytes=32)
    challenge = _hex(data["device_challenge_hex"], "device-challenge",
                     exact_bytes=32)
    hs = _hex(data["ha_proof_signature_der_hex"], "ha-signature",
              minimum_bytes=8, maximum_bytes=80)
    ds = _hex(data["device_proof_signature_der_hex"], "device-signature",
              minimum_bytes=8, maximum_bytes=80)
    try:
        ha_key.verify(hs, HA_DOMAIN + sid + ha_pub + hn,
                      ec.ECDSA(hashes.SHA256()))
        device_key.verify(ds, DEVICE_DOMAIN + sid + challenge + device_pub,
                          ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        raise TranscriptRejected("invalid-signature") from None

    payload = (DOMAIN + bytes((VERSION,)) + sid + epoch + tx +
               bytes((len(did),)) + did + ha_pub + device_pub + hn +
               challenge + bytes((len(hs),)) + hs +
               bytes((len(ds),)) + ds)
    return {
        "transcript_sha256": sha256(payload).hexdigest(),
        "ha_key_sha256": sha256(ha_pub).hexdigest(),
        "device_key_sha256": sha256(device_pub).hexdigest(),
        "canonical_payload_hex": payload.hex(),
    }


def production_pairing_enabled() -> bool:
    return False


def device_write_enabled() -> bool:
    return False
