"""Strict read-only parser for Config v2 Security2 pairing readiness.

This model never accepts credentials, enters pairing mode, derives a shared
secret, or grants authentication. A firmware's self-advertisement does not
establish device identity or allow firmware writes.
"""
from __future__ import annotations

from typing import Any

class PairingStatusError(ValueError):
    """Remote pairing metadata does not match the safe preview contract."""

SCHEME = "protocomm-security2-srp6a-aes256gcm"
_EXPECTED = {
    "api_version": "omote-pairing-v1-preview",
    "state": "disabled",
    "security_scheme": SCHEME,
    "transport": "not-started",
    "transport_port": 0,
    "pairing_window_open": False,
    "paired": False,
    "device_identity_available": False,
    "touch_approval_required": True,
    "session_ready": False,
    "deployment_enabled": False,
}

def summarize_pairing_status(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize status from legacy 404 or the *disabled* firmware prototype."""
    if payload is None:
        return {
            "available": False, "api_version": "",
            "scheme": "", "status": "not-supported",
            "encrypted_session_ready": False,
            "pairing_enabled": False, "device_identity_verified": False,
            "deployment_enabled": False,
            "explanation": "The installed firmware has no Config v2 pairing-status endpoint.",
        }
    if not isinstance(payload, dict):
        raise PairingStatusError("Pairing status must be a JSON object")
    # Require exact fields and types; e.g. 0 is NOT False and True is NOT 1.
    # A future authenticated protocol must have a separately reviewed schema.
    if payload.keys() != _EXPECTED.keys() or any(
        type(payload[key]) is not type(value) or payload[key] != value
        for key, value in _EXPECTED.items()
    ):
        raise PairingStatusError(
            "Unknown or unsafe pairing capabilities; no pairing is permitted"
        )
    return {
        "available": True,
        "api_version": payload["api_version"],
        "scheme": payload["security_scheme"],
        "status": payload["state"],
        "encrypted_session_ready": False,
        "pairing_enabled": False,
        "device_identity_verified": False,
        "deployment_enabled": False,
        "explanation": (
            "Security2 SRP6a/AES-GCM is planned and ephemeral SRP material is "
            "being implemented in the firmware feature branch. No encrypted "
            "pairing listener, peer identity verification, or trusted session "
            "is available yet."
        ),
    }
