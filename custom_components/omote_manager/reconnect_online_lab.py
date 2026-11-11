"""Isolated reconnect LAB client; not registered with Home Assistant.

An injected transport is necessary. The two pinned identities must come from a
separate physically approved test enrollment; this module does not enroll,
persist, authorize pairing, expose config APIs or manage device storage.
The protocol is experimental and not suitable for production use.
"""
from __future__ import annotations

import asyncio
from hashlib import sha256
from secrets import token_bytes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .reconnect_crypto_draft import public_bytes, transcript, sign, derive

class ReconnectLabError(RuntimeError):
    """Sanitized failure; never includes key, nonce, response, or network body."""

async def run_reconnect_lab(*, transport, ha_key, device_public, ack_lab_only=False):
    """One bounded attempt with independently supplied pinned public keys.

    Transport implements async exchange(stage, message), with stages 'open'
    and 'confirm'. Client requires a fresh server challenge and ephemeral key,
    verifies the exact pinned server signature and checks an AES-GCM response.
    No automatic retry: a failed/uncertain exchange destroys this session.
    """
    if ack_lab_only is not True:
        raise ReconnectLabError('explicit-lab-consent')
    stage = 'local-preflight'
    try:
        if not isinstance(ha_key, ec.EllipticCurvePrivateKey) or not isinstance(ha_key.curve, ec.SECP256R1):
            raise ValueError('invalid HA key')
        if type(device_public) is not bytes:
            raise ValueError('invalid device pin')
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), device_public)
        ha_public = public_bytes(ha_key.public_key())
        ephemeral = ec.generate_private_key(ec.SECP256R1())
        ha_ephemeral = public_bytes(ephemeral.public_key())
        ha_challenge = token_bytes(32)
        stage = 'open'
        reply = await asyncio.wait_for(transport.exchange('open', {
            'ha_static': ha_public, 'ha_ephemeral': ha_ephemeral,
            'ha_challenge': ha_challenge,
        }), timeout=8)
        if type(reply) is not dict or set(reply) != {'device_ephemeral', 'device_challenge', 'device_signature'}:
            raise ValueError('invalid open reply')
        fields = dict(ha_static=ha_public, device_static=device_public,
                      ha_ephemeral=ha_ephemeral, device_ephemeral=reply['device_ephemeral'],
                      ha_challenge=ha_challenge, device_challenge=reply['device_challenge'])
        context = transcript(**fields)
        ha_signature = sign(ha_key, 'ha', context)
        stage = 'verify-device'
        send_key, receive_key = derive(role='ha', own_ephemeral=ephemeral, **fields,
             ha_signature=ha_signature, device_signature=reply['device_signature'],
             pinned_ha_sha256=sha256(ha_public).digest(),
             pinned_device_sha256=sha256(device_public).digest())
        # A new ECDH secret and distinct directional keys are required each run.
        # Counter zero is used exactly once in each direction in this LAB.
        nonce = bytes(12)
        aad = sha256(context).digest()
        probe = token_bytes(32)
        encrypted = AESGCM(send_key).encrypt(nonce, probe, aad)
        stage = 'confirm'
        confirmed = await asyncio.wait_for(transport.exchange('confirm', {
            'ha_signature': ha_signature, 'ciphertext': encrypted,
        }), timeout=8)
        if type(confirmed) is not bytes or len(confirmed) != 48:
            raise ValueError('invalid encrypted response')
        if AESGCM(receive_key).decrypt(nonce, confirmed, aad) != probe:
            raise ValueError('probe mismatch')
        return {'lab_only': True, 'encrypted_reconnect_verified': True,
                'paired': False, 'trusted': False,
                'deployment_enabled': False, 'ota_enabled': False}
    except Exception:
        raise ReconnectLabError(stage) from None
