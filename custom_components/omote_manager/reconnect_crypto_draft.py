"""Offline mutual P-256 reconnect transcript and key derivation experiment.

No network endpoint, trust store, pairing grant or runtime integration. Both
parties must supply independently pinned static public keys, fresh challenges
and freshly generated ephemeral keys. This is not a reviewed wire protocol.
"""
from hashlib import sha256

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CONTEXT = b"OMOTE-RECONNECT-DRAFT-V1\x00"
HA_DOMAIN = b"OMOTE-RECONNECT-HA-V1\x00"
DEVICE_DOMAIN = b"OMOTE-RECONNECT-DEVICE-V1\x00"
KEY_DOMAIN = b"OMOTE-RECONNECT-KEYS-V1\x00"

class ReconnectRejected(ValueError):
    """Malformed, unpinned or incorrectly signed reconnect evidence."""

def public_bytes(key):
    return key.public_bytes(serialization.Encoding.X962,
                            serialization.PublicFormat.UncompressedPoint)

def _point(value):
    if type(value) is not bytes or len(value) != 65 or value[0] != 4:
        raise ReconnectRejected("invalid-point")
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), value)
    except ValueError:
        raise ReconnectRejected("invalid-point") from None

def transcript(*, ha_static, device_static, ha_ephemeral, device_ephemeral,
               ha_challenge, device_challenge):
    fields = (ha_static, device_static, ha_ephemeral, device_ephemeral)
    for value in fields:
        _point(value)
    for challenge in (ha_challenge, device_challenge):
        if type(challenge) is not bytes or len(challenge) != 32 or not any(challenge):
            raise ReconnectRejected("invalid-challenge")
    if ha_challenge == device_challenge or ha_ephemeral == device_ephemeral:
        raise ReconnectRejected("reflected-transcript")
    return CONTEXT + b"".join(fields) + ha_challenge + device_challenge

def sign(key, role, context):
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ReconnectRejected("invalid-signing-key")
    if role not in ("ha", "device") or type(context) is not bytes or len(context) != len(CONTEXT) + 324 or not context.startswith(CONTEXT):
        raise ReconnectRejected("invalid-signing-context")
    return key.sign((HA_DOMAIN if role == "ha" else DEVICE_DOMAIN) + context,
                    ec.ECDSA(hashes.SHA256()))

def derive(*, role, own_ephemeral, ha_static, device_static, ha_ephemeral,
           device_ephemeral, ha_challenge, device_challenge, ha_signature,
           device_signature, pinned_ha_sha256, pinned_device_sha256):
    context = transcript(ha_static=ha_static, device_static=device_static,
                         ha_ephemeral=ha_ephemeral, device_ephemeral=device_ephemeral,
                         ha_challenge=ha_challenge, device_challenge=device_challenge)
    if (type(pinned_ha_sha256) is not bytes or len(pinned_ha_sha256) != 32 or
        type(pinned_device_sha256) is not bytes or len(pinned_device_sha256) != 32 or
        sha256(ha_static).digest() != pinned_ha_sha256 or
        sha256(device_static).digest() != pinned_device_sha256):
        raise ReconnectRejected("identity-pin-mismatch")
    if role not in ("ha", "device") or not isinstance(own_ephemeral, ec.EllipticCurvePrivateKey) or not isinstance(own_ephemeral.curve, ec.SECP256R1):
        raise ReconnectRejected("invalid-ephemeral-key")
    own = ha_ephemeral if role == "ha" else device_ephemeral
    peer = device_ephemeral if role == "ha" else ha_ephemeral
    if public_bytes(own_ephemeral.public_key()) != own:
        raise ReconnectRejected("ephemeral-key-mismatch")
    try:
        _point(ha_static).verify(ha_signature, HA_DOMAIN + context, ec.ECDSA(hashes.SHA256()))
        _point(device_static).verify(device_signature, DEVICE_DOMAIN + context, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError):
        raise ReconnectRejected("invalid-peer-signature") from None
    shared = own_ephemeral.exchange(ec.ECDH(), _point(peer))
    material = HKDF(algorithm=hashes.SHA256(), length=64, salt=sha256(context).digest(), info=KEY_DOMAIN).derive(shared)
    return (material[:32], material[32:]) if role == "ha" else (material[32:], material[:32])
