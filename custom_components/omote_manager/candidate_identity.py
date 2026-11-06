"""Administrator-prepared, persistent HA *candidate* P-256 identity per OMOTE.

This is not pairing, a trusted credential, a live connection, or an
authorization mechanism. No network methods or firmware writes exist here.

Private DER keys reside in HA's local .storage (normal HA storage controls,
NOT hardware-backed or encrypted at rest). A full HA backup can copy them.
They must never be placed in OMOTE JSON profiles, diagnostic responses,
websocket replies, logs or user-exported deployment packages.

A corrupt, mismatched or unreadable identity fails closed. Never silently
rotate a saved key, or create one on HA startup.
"""
from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
import hashlib
import re
import secrets
from typing import Any

_VERSION = 1
_RECORD_FORMAT = "omote-ha-candidate-p256-v1"
_DOMAIN = b"OMOTE-SEC2-LAB-HA-PROOF-V1"
_MAX_IDENTITIES = 32
_ENTRY_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class CandidateIdentityError(ValueError):
    """A candidate key cannot safely be read, saved or used."""


def _crypto():
    # Lazy import: the read-only integration must continue working if this
    # optional, administrator-only development feature cannot load crypto.
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    return hashes, serialization, ec


def _public_bytes(private_key) -> bytes:
    _, serialization, ec = _crypto()
    public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    if len(public) != 65 or public[0] != 0x04:
        raise CandidateIdentityError("Invalid P-256 public key representation")
    return public


def _make_record() -> dict[str, str]:
    _, serialization, ec = _crypto()
    key = ec.generate_private_key(ec.SECP256R1())
    der = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return {
        "format": _RECORD_FORMAT,
        "private_der_b64": base64.b64encode(der).decode("ascii"),
        "fingerprint": hashlib.sha256(_public_bytes(key)).hexdigest(),
    }


def _read_record(record: Any):
    _, serialization, ec = _crypto()
    if not isinstance(record, dict) or set(record) != {
        "format", "private_der_b64", "fingerprint"
    } or record["format"] != _RECORD_FORMAT:
        raise CandidateIdentityError("Unsupported candidate-key record")
    stored = record["fingerprint"]
    private_b64 = record["private_der_b64"]
    if not isinstance(stored, str) or not _FINGERPRINT.fullmatch(stored):
        raise CandidateIdentityError("Invalid candidate-key fingerprint")
    if not isinstance(private_b64, str) or not 128 <= len(private_b64) <= 700:
        raise CandidateIdentityError("Invalid candidate-key encoding")
    try:
        der = base64.b64decode(private_b64, validate=True)
        if not 96 <= len(der) <= 500:
            raise ValueError("Invalid private-key length")
        key = serialization.load_der_private_key(der, password=None)
    except (ValueError, TypeError, OverflowError) as exc:
        raise CandidateIdentityError("Corrupt candidate-key storage") from None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise CandidateIdentityError("Unexpected private-key algorithm")
    derived = hashlib.sha256(_public_bytes(key)).hexdigest()
    if not secrets.compare_digest(stored, derived):
        raise CandidateIdentityError("Candidate fingerprint/private key mismatch")
    return key


def _validate_state(raw: Any) -> dict:
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "identities"}:
        raise CandidateIdentityError("Unsupported candidate identity store")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != _VERSION:
        raise CandidateIdentityError("Unexpected candidate store version")
    ids = raw["identities"]
    if not isinstance(ids, dict) or len(ids) > _MAX_IDENTITIES:
        raise CandidateIdentityError("Malformed candidate identity inventory")
    for entry_id, record in ids.items():
        if not isinstance(entry_id, str) or not _ENTRY_ID.fullmatch(entry_id):
            raise CandidateIdentityError("Invalid candidate identity reference")
        _read_record(record)
    return deepcopy(raw)


def _blank() -> dict:
    return {"schema_version": _VERSION, "identities": {}}


def _status(record: dict | None) -> dict:
    # The complete HTTP/WebSocket-facing response is a non-secret projection.
    return {
        "prepared": record is not None,
        "fingerprint": record["fingerprint"] if record is not None else "",
        "key_type": "P-256 candidate only",
        "trusted": False,
        "pairing_enabled": False,
        "deployment_enabled": False,
        "nvs_or_device_updated": False,
        "storage": "Home Assistant local .storage (not encrypted at rest)",
    }


class CandidateIdentityStore:
    """Persistent per-entry identities, created only on admin opt-in.

    The backing object implements HA Store.async_load()/async_save().
    Error state is terminal within this HA process to avoid accidentally
    replacing lost credentials or permitting untrusted recovery.
    """

    def __init__(self, backing_store):
        self._store = backing_store
        self._state = _blank()
        self._lock = asyncio.Lock()
        self._load_error: str | None = "not_loaded"

    async def async_load(self) -> None:
        async with self._lock:
            try:
                raw = await self._store.async_load()
                self._state = _blank() if raw is None else _validate_state(raw)
                self._load_error = None
            except Exception as exc:
                # Fail closed without disclosing key material. The ordinary
                # read-only OMOTE integration must still be able to start.
                self._state = _blank()
                self._load_error = "candidate_identity_storage_unavailable"

    def status(self, entry_id: str) -> dict:
        if not isinstance(entry_id, str) or not _ENTRY_ID.fullmatch(entry_id):
            raise CandidateIdentityError("Invalid OMOTE entry")
        if self._load_error is not None:
            raise CandidateIdentityError("Candidate key storage unavailable")
        return _status(self._state["identities"].get(entry_id))

    async def async_prepare(self, entry_id: str) -> dict:
        """Create ONCE after a real admin UI click, never at startup."""
        if not isinstance(entry_id, str) or not _ENTRY_ID.fullmatch(entry_id):
            raise CandidateIdentityError("Invalid OMOTE entry")
        async with self._lock:
            if self._load_error is not None:
                raise CandidateIdentityError("Candidate key storage unavailable")
            known = self._state["identities"].get(entry_id)
            if known is not None:
                # A second click or retry must NEVER silently rotate identity.
                return {**_status(known), "created": False}
            if len(self._state["identities"]) >= _MAX_IDENTITIES:
                raise CandidateIdentityError("Candidate identity inventory full")
            try:
                record = _make_record()
            except Exception:
                raise CandidateIdentityError("Unable to generate candidate P-256 key") from None
            next_state = deepcopy(self._state)
            next_state["identities"][entry_id] = record
            try:
                await self._store.async_save(next_state)
            except Exception:
                # Do not publish an unsaved identity; do not log private data.
                raise CandidateIdentityError("Unable to save candidate identity") from None
            self._state = next_state
            return {**_status(record), "created": True}

    def make_lab_ha_proof(
        self, entry_id: str, session_id: int
    ) -> bytes:
        """Offline wire-compatible LAB proof, NOT a WebSocket operation.

        Future authenticated transport may use this only after Security2.
        No public endpoint signs arbitrary challenges or exposes this method.
        """
        if type(session_id) is not int or not 0 <= session_id <= 0xFFFFFFFF:
            raise CandidateIdentityError("Invalid encrypted session ID")
        if self._load_error is not None:
            raise CandidateIdentityError("Candidate key storage unavailable")
        record = self._state["identities"].get(entry_id)
        if record is None:
            raise CandidateIdentityError("No prepared candidate identity")
        key = _read_record(record)
        hashes, _, ec = _crypto()
        public = _public_bytes(key)
        nonce = secrets.token_bytes(32)
        message = _DOMAIN + session_id.to_bytes(4, "big") + public + nonce
        signature = key.sign(message, ec.ECDSA(hashes.SHA256()))
        if not 8 <= len(signature) <= 80:
            raise CandidateIdentityError("Unexpected signature encoding")
        return b"\x01" + public + nonce + len(signature).to_bytes(2, "big") + signature
