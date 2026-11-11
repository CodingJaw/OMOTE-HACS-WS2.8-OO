"""Isolated, opt-in Security2 LAB interoperability orchestrator.

The v2 diagnostic is reachable only through an admin-only, default-off LAB
WebSocket. It is NEVER production pairing. Callers supply the bundled
Security2 implementation, scoped transport and a locally displayed PIN.
Only fixed, unprivileged LAB endpoints on port 18082 are accessed.

The Waveshare software device key is NOT hardware protected. Its verified
fingerprint is diagnostic only, never a trusted identity or enrollment.
"""
from __future__ import annotations

import asyncio
from hashlib import sha256
import ipaddress
import json
import re
import secrets

from .candidate_identity import CandidateIdentityError, CandidateIdentityStore

_LAB_PORT = 18082
_LAB_VERSION = "omote-sec2-lab-v1"
_LAB_TIMEOUT_SECONDS = 8
_LAB_TOTAL_SECONDS = 40
_LAB_RESPONSE_MAX = 4096
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

    async def bounded(endpoint: str, payload):
        reply = await asyncio.wait_for(
            transport.send_data(endpoint, payload), timeout=_LAB_TIMEOUT_SECONDS
        )
        if not isinstance(reply, str) or len(reply) > _LAB_RESPONSE_MAX:
            raise ValueError("Invalid or oversized LAB response")
        return reply

    async def exchange():
        nonlocal stage, transport
        transport = transport_factory(f"{host}:{_LAB_PORT}")
        stage = "version"
        raw = await bounded("proto-ver", "-")
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
            response = await bounded("prov-session", request)
            if response is None:
                raise ValueError("Missing Security2 response")
        else:
            raise ValueError("Security2 frame limit")

        stage = "encrypted-probe"
        reply = await bounded(
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
        reply = await bounded(
            "omote-ha-proof", security.encrypt_data(proof).decode("latin-1")
        )
        if security.decrypt_data(reply.encode("latin-1")) != _HA_REPLY:
            raise ValueError("Candidate proof rejected")

        stage = "device-proof"
        challenge = b"\x01" + secrets.token_bytes(32)
        reply = await bounded(
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
    try:
        return await asyncio.wait_for(exchange(), timeout=_LAB_TOTAL_SECONDS)
    except Exception:
        raise LabSessionError(stage) from None
    finally:
        if transport is not None:
            # New HA transport is async; older offline mock is sync.
            # Always release open session sockets on cancellation/error.
            aclose = getattr(transport, "aclose", None)
            if callable(aclose):
                await aclose()
            else:
                connection = getattr(transport, "conn", None)
                if connection is not None:
                    connection.close()


async def run_tx2_lab_session(
    *, host: str, pin: str, entry_id: str, identities: CandidateIdentityStore,
    security_factory, transport_factory, ack_lab_only: bool = False,
) -> dict:
    """Exercise saved HA key and physical review on patch-1 LAB firmware.

    This is diagnostic only: the device key is untrusted, no credentials are
    persisted, and no reconnect, pairing, deployment or OTA is authorized.
    """
    from .sec2_tx_v2_lab import LabV2Transaction

    if ack_lab_only is not True:
        raise LabSessionError("explicit-lab-consent")
    try:
        ipaddress.IPv4Address(host)
        if type(pin) is not str or re.fullmatch(r"[0-9]{6}", pin) is None:
            raise ValueError("Invalid PIN")
        prepared = identities.status(entry_id)
        if not prepared["prepared"] or prepared["trusted"]:
            raise ValueError("Missing candidate")
    except (ValueError, CandidateIdentityError, KeyError, TypeError):
        raise LabSessionError("local-preflight") from None

    stage = "transport"
    transport = None

    async def bounded(endpoint, payload):
        reply = await asyncio.wait_for(
            transport.send_data(endpoint, payload), timeout=_LAB_TIMEOUT_SECONDS)
        if type(reply) is not str or len(reply) > _LAB_RESPONSE_MAX:
            raise ValueError("Invalid LAB response")
        return reply

    async def exchange():
        nonlocal stage, transport
        transport = transport_factory(f"{host}:{_LAB_PORT}")
        stage = "version"
        metadata = json.loads(await bounded("proto-ver", "-"))["prov"]
        if (type(metadata) is not dict or metadata.get("ver") != _LAB_VERSION
                or type(metadata.get("sec_patch_ver")) is not int
                or metadata["sec_patch_ver"] != 1):
            raise ValueError("Patch-1 laboratory firmware required")
        stage = "security2"
        security = security_factory(sec_patch_ver=1, username="omote-ha",
                                    password=pin, verbose=False)
        response = None
        for _ in range(4):
            request = security.security_session(response)
            if request is None:
                break
            response = await bounded("prov-session", request)
        else:
            raise ValueError("Security2 frame limit")

        async def encrypted(endpoint, payload):
            request = security.encrypt_data(payload).decode("latin-1")
            reply = await bounded(endpoint, request)
            return security.decrypt_data(reply.encode("latin-1"))

        stage = "encrypted-probe"
        if await encrypted("omote-probe", b"OMOTE-SEC2-PROBE-V1") != b"OMOTE-SEC2-OK-V1":
            raise ValueError("Probe failed")
        stage = "transaction-open"
        tx = LabV2Transaction(transport.headers.get("Cookie", ""), identities, entry_id)
        if sha256(tx._ha_pub).hexdigest() != prepared["fingerprint"]:
            raise ValueError("Candidate identity changed")
        opened = await encrypted("omote-tx2-open", tx.open_request())
        stage = "transaction-commit"
        commit = await encrypted("omote-tx2-commit", tx.commit_request(opened))
        tx.check_commit(commit)
        fingerprints = tx.verified_public_fingerprints()
        stage = "touch-review"
        # Physical review is bounded independently; no retries of failed calls.
        deadline = asyncio.get_running_loop().time() + 45
        while asyncio.get_running_loop().time() < deadline:
            reply = await encrypted("omote-tx2-review", tx.review_request())
            if tx.check_review_reply(reply):
                break
            await asyncio.sleep(1)
        else:
            raise ValueError("Touch review expired")
        stage = "touch-receipt"
        receipt = await encrypted("omote-tx2-touch-receipt", tx.touch_receipt_request())
        tx.check_touch_receipt_reply(receipt)
        return {
            "lab_only": True,
            "encrypted_probes_passed": True,
            "touch_receipt_verified": True,
            "candidate_ha_fingerprint": fingerprints["ha"],
            "untrusted_device_fingerprint": fingerprints["device"],
            "trusted": False, "paired": False,
            "deployment_enabled": False, "ota_enabled": False,
        }

    try:
        return await asyncio.wait_for(exchange(), timeout=75)
    except Exception:
        raise LabSessionError(stage) from None
    finally:
        if transport is not None:
            await transport.aclose()
