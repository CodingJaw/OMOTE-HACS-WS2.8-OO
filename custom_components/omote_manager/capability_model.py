"""Fail-closed, read-only interpretation of OMOTE config-v2 capabilities.

This module NEVER enables remote mutations. A future firmware's affirmative
flags are not proof of secure pairing, transaction correctness, hardware
qualification, or compatibility with a specific HA integration version.
"""
from __future__ import annotations

from typing import Any

class CapabilitiesError(ValueError):
    """Malformed or unsafe capability advertisement."""

_REQUIRED_FIELDS = (
    "api_version", "auth_mode", "transaction_support", "rollback_support",
    "write_protection_enabled", "max_file_bytes", "max_transaction_bytes",
    "available_staging_bytes", "device_id", "firmware_build",
    "active_revision_sha256", "previous_revision_sha256",
)
_SHA_CHARS = frozenset("0123456789abcdef")


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in _SHA_CHARS for char in value
    )


def _quantity(obj: dict, key: str) -> int:
    value = obj.get(key)
    if type(value) is not int or value < 0 or value > 2**32 - 1:
        raise CapabilitiesError(f"Invalid capability limit: {key}")
    return value


def summarize_capabilities(payload: dict | None) -> dict[str, Any]:
    """Normalize one v2 preview, keeping all remote writes unavailable.

    An absent endpoint means a legacy read-only device, not a permission to
    fall back to unauthenticated v1 mutations.
    """
    if payload is None:
        return {
            "generation": "legacy-v1",
            "api_version": "omote-config-v1",
            "firmware_build": "",
            "auth_mode": "not-advertised",
            "device_identity_available": False,
            "transaction_support": False,
            "rollback_support": False,
            "write_protection_enabled": False,
            "max_file_bytes": 0,
            "max_transaction_bytes": 0,
            "available_staging_bytes": 0,
            "active_revision_available": False,
            "preview_only": False,
            "deployment_enabled": False,
            "explanation": (
                "Firmware uses the legacy read API; authenticated v2 "
                "deployment has not been advertised."
            ),
        }

    if not isinstance(payload, dict):
        raise CapabilitiesError("Capabilities must be a JSON object")
    for key in _REQUIRED_FIELDS:
        if key not in payload:
            raise CapabilitiesError(f"Missing capability field: {key}")
    version = payload["api_version"]
    if not isinstance(version, str) or len(version) > 80 or not version.startswith(
        "omote-config-v2"
    ):
        raise CapabilitiesError("Unknown configuration capability API")
    auth_mode = payload["auth_mode"]
    firmware = payload["firmware_build"]
    device_id = payload["device_id"]
    if not isinstance(auth_mode, str) or len(auth_mode) > 80:
        raise CapabilitiesError("Invalid authentication capability")
    if not isinstance(firmware, str) or len(firmware) > 120:
        raise CapabilitiesError("Invalid firmware identifier")
    if not isinstance(device_id, str) or len(device_id) > 128:
        raise CapabilitiesError("Invalid device identity")
    for flag in ("transaction_support", "rollback_support", "write_protection_enabled"):
        if type(payload[flag]) is not bool:
            raise CapabilitiesError(f"Invalid boolean capability: {flag}")
    active = payload["active_revision_sha256"]
    previous = payload["previous_revision_sha256"]
    if not isinstance(active, str) or (active and not _digest(active)):
        raise CapabilitiesError("Invalid active revision SHA-256")
    if not isinstance(previous, str) or (previous and not _digest(previous)):
        raise CapabilitiesError("Invalid previous revision SHA-256")
    return {
        "generation": "preview" if version.endswith("-preview") else "v2-advertised",
        "api_version": version,
        "firmware_build": firmware,
        "auth_mode": auth_mode,
        "device_identity_available": bool(device_id),
        "transaction_support": payload["transaction_support"],
        "rollback_support": payload["rollback_support"],
        "write_protection_enabled": payload["write_protection_enabled"],
        "max_file_bytes": _quantity(payload, "max_file_bytes"),
        "max_transaction_bytes": _quantity(payload, "max_transaction_bytes"),
        "available_staging_bytes": _quantity(payload, "available_staging_bytes"),
        "active_revision_available": bool(active),
        "preview_only": version.endswith("-preview"),
        # Cannot be made true by untrusted firmware metadata alone.
        "deployment_enabled": False,
        "explanation": (
            "Read-only v2 preview; secure pairing and deployment are not implemented."
            if version.endswith("-preview") else
            "Firmware advertises v2 features, but Home Assistant deployment "
            "remains disabled until the final authenticated protocol and "
            "hardware recovery tests are approved."
        ),
    }
