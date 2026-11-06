"""Isolated, opt-in Security2 LAB interoperability orchestrator.

Not registered by OMOTE Manager, not a WebSocket or service, and NEVER
production pairing. A caller must explicitly provide the official ESP-IDF
Security2/Transport_HTTP implementations and a locally displayed PIN.
Only fixed, unprivileged LAB endpoints on port 18082 are accessed.

The Waveshare software device key is NOT hardware protected. Its verified
fingerprint is diagnostic only, never a trusted identity or enrollment.
"""
from __future__ import annotations

from hashlib import sha256
import ipaddress
import json
import re
import secrets

from .candidate_identity import CandidateIdentityError, CandidateIdentityStore

_LAB_PORT = 18082
_LAB_VERSION = "omote-sec2-lab-v1"
_HA_REPLY = b"OMOTE-LAB-HA-PROOF-OK-V1"
_DEVICE_DOMAIN = b"OMOTE-SEC2-LAB-DEVICE-PROOF-V1"
_COOKIE = re.compile(r"session=(?:0|[1-9][0-9]{0,9})\Z", re.ASCII)


class LabSessionError(RuntimeError):
    """A sanitized stage identifier; never includes PINs, headers or bodies."""

    def __init__(self, stage: str):
        self.stage = stage
        super().__init__(f"Security2 laboratory stage failed: {stage}")


def _session_id(cookie: str) -> int:
    if not isinstance(cookie, str) or _COOKIE.fullmatch(cookie) is None:
        raise ValueError("Invalid cookie")
    value = int(cookie[8:])
    if value > 0xFFFFFFFF:
        raise ValueError("Out-of-range session")
    return value


def _device_proof(session_id: int, challenge: bytes, response: bytes) -> str:
    """Verify session-bound signature; resulting fingerprint is UNTRUSTED."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    if (type(session_id) is not int or not 0 <= session_id <= 0xFFFFFFFF
            or type(challenge) is not bytes or len(challenge) != 33
            or challenge[0] != 1 or type(response) is not bytes
            or not 76 <= len(response) <= 148
            or response[0] != 1 or response[1] != 4):
        raise ValueError("Malformed device proof")
    public = response[1:66]
    n = int.from_bytes(response[66:68], "big")
    if not 8 <= n <= 80 or len(response) != 68 + n:
        raise ValueError("Malformed signature length")
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
    signed = _DEVICE_DOMAIN + session_id.to_bytes(4, "big") + challenge[1:] + public
    key.verify(response[68:], signed, ec.ECDSA(hashes.SHA256()))
    return sha256(public).hexdigest()


async def run_lab_session(
    *, host: str, pin: str, entry_id: str, identities: CandidateIdentityStore,
    security_factory, transport_factory, ack_lab_only: bool = False,
) -> dict:
    """Perform a single *experimental* encrypted session using saved HA key.

    Factories must be supplied by explicitly invoked server-side LAB tooling.
    Do not publish this function as an HA WebSocket/HTTP/service action.
    Never auto-retry: each SRP message charges the device's persistent quota.
    Does not pin identities or grant trust; all error details are sanitized.
    """
    if ack_lab_only is not True:
        raise LabSessionError("explicit-lab-consent")
    try:
        ipaddress.IPv4Address(host)
        if not isinstance(pin, str) or re.fullmatch(r"[0-9]{6}", pin) is None:
            raise ValueError("Invalid local PIN")
        prepared = identities.status(entry_id)
        if not prepared["prepared"] or prepared["trusted"]:
            raise ValueError("Missing untrusted candidate")
    except (ValueError, CandidateIdentityError, KeyError, TypeError):
        raise LabSessionError("local-preflight") from None

    stage = "transport"
    transport = None
    try:
        transport = transport_factory(f"{host}:{_LAB_PORT}")
        stage = "version"
        raw = await transport.send_data("proto-ver", "-")
        if not isinstance(raw, str) or len(raw) > 1024:
            raise ValueError("Invalid lab version")
        metadata = json.loads(raw)["prov"]
        if (not isinstance(metadata, dict)
                or metadata.get("ver") != _LAB_VERSION
                or type(metadata.get("sec_patch_ver")) is not int
                or metadata["sec_patch_ver"] not in (0, 1)):
            raise ValueError("Incompatible lab")
        stage = "security2"
        security = security_factory(
            sec_patch_ver=metadata["sec_patch_ver"],
            username="omote-ha", password=pin, verbose=False,
        )
        response = None
        for _ in range(4):
            request = security.security_session(response)
            if request is None:
                break
            response = await transport.send_data("prov-session", request)
            if response is None:
                raise ValueError("Missing Security2 response")
        else:
            raise ValueError("Security2 frame limit")

        stage = "encrypted-probe"
        reply = await transport.send_data(
            "omote-probe", security.encrypt_data(b"OMOTE-SEC2-PROBE-V1").decode("latin-1")
        )
        if security.decrypt_data(reply.encode("latin-1")) != b"OMOTE-SEC2-OK-V1":
            raise ValueError("Probe failed")
        stage = "session-binding"
        sid = _session_id(transport.headers.get("Cookie", ""))
        proof = identities.make_lab_ha_proof(entry_id, sid)
        if sha256(proof[1:66]).hexdigest() != prepared["fingerprint"]:
            raise ValueError("Candidate changed")

        stage = "candidate-proof"
        reply = await transport.send_data(
            "omote-ha-proof", security.encrypt_data(proof).decode("latin-1")
        )
        if security.decrypt_data(reply.encode("latin-1")) != _HA_REPLY:
            raise ValueError("Candidate proof rejected")

        stage = "device-proof"
        challenge = b"\x01" + secrets.token_bytes(32)
        reply = await transport.send_data(
            "omote-device-proof", security.encrypt_data(challenge).decode("latin-1")
        )
        fingerprint = _device_proof(
            sid, challenge, security.decrypt_data(reply.encode("latin-1"))
        )
        return {
            "lab_only": True,
            "encrypted_probes_passed": True,
            "candidate_ha_fingerprint": prepared["fingerprint"],
            "untrusted_device_fingerprint": fingerprint,
            "trusted": False,
            "paired": False,
            "deployment_enabled": False,
            "ota_enabled": False,
        }
    except Exception:
        raise LabSessionError(stage) from None
    finally:
        if transport is not None:
            connection = getattr(transport, "conn", None)
            if connection is not None:
                connection.close()
