"""Fail-closed, read-only OMOTE configuration capability normalization.

Both the legacy v2-preview with retired A/B compatibility placeholders and the
single-active v2 preview are accepted. Neither metadata nor a positive firmware
flag can authorize writes, pairing, deployment or recovery resends.
"""
from __future__ import annotations

from typing import Any


class CapabilitiesError(ValueError):
    """Malformed or unsafe capability advertisement."""


_REQUIRED_FIELDS = (
    "api_version", "auth_mode", "transaction_support",
    "write_protection_enabled", "max_file_bytes", "max_transaction_bytes",
    "available_staging_bytes", "device_id", "firmware_build",
    "active_revision_sha256",
)
_SHA_CHARS = frozenset("0123456789abcdef")
_RECOVERY_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in _SHA_CHARS for char in value
    )


def _revision(value: Any, name: str) -> str:
    if not isinstance(value, str) or (value and not _digest(value)):
        raise CapabilitiesError(f"Invalid {name} SHA-256")
    return value


def _quantity(obj: dict, key: str) -> int:
    value = obj.get(key)
    if type(value) is not int or value < 0 or value > 2**32 - 1:
        raise CapabilitiesError(f"Invalid capability limit: {key}")
    return value


def summarize_capabilities(payload: dict | None) -> dict[str, Any]:
    """Normalize optional v2 metadata. All variants remain non-deployable."""
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
                "Firmware uses the legacy read API; secure v2 deployment "
                "is not available."
            ),
        }
    if not isinstance(payload, dict):
        raise CapabilitiesError("Capabilities must be a JSON object")
    for key in _REQUIRED_FIELDS:
        if key not in payload:
            raise CapabilitiesError(f"Missing capability field: {key}")
    version = payload["api_version"]
    if (
        not isinstance(version, str)
        or len(version) > 80
        or not version.startswith("omote-config-v2")
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
    for flag in ("transaction_support", "write_protection_enabled"):
        if type(payload[flag]) is not bool:
            raise CapabilitiesError(f"Invalid boolean capability: {flag}")
    # Old preview fields are optional and explicitly retired. Validate them
    # when present, but never present them as an active rollback capability.
    if "rollback_support" in payload and type(payload["rollback_support"]) is not bool:
        raise CapabilitiesError("Invalid retired rollback flag")
    if "previous_revision_sha256" in payload:
        _revision(payload["previous_revision_sha256"], "retired previous revision")
    if "legacy_http_writes_disabled" in payload and type(
        payload["legacy_http_writes_disabled"]
    ) is not bool:
        raise CapabilitiesError("Invalid legacy HTTP write-protection flag")
    active = _revision(payload["active_revision_sha256"], "active revision")
    return {
        "generation": "preview" if version.endswith("-preview") else "v2-advertised",
        "api_version": version,
        "firmware_build": firmware,
        "auth_mode": auth_mode,
        "device_identity_available": bool(device_id),
        "transaction_support": payload["transaction_support"],
        "rollback_support": False,
        "write_protection_enabled": payload["write_protection_enabled"],
        "max_file_bytes": _quantity(payload, "max_file_bytes"),
        "max_transaction_bytes": _quantity(payload, "max_transaction_bytes"),
        "available_staging_bytes": _quantity(payload, "available_staging_bytes"),
        "active_revision_available": bool(active),
        "preview_only": version.endswith("-preview"),
        "deployment_enabled": False,
        "explanation": (
            "Read-only v2 preview; secure pairing and deployment are not implemented."
            if version.endswith("-preview") else
            "Firmware advertises v2 features, but deployment remains disabled "
            "until authenticated transactions and physical recovery are approved."
        ),
    }


def summarize_storage_status(payload: dict | None) -> dict[str, Any]:
    """Read-only capacity and single-active state, including legacy fallback.

    A/B compatibility placeholders are not required or exposed. Invalid
    recovery status is rejected rather than interpreted as a healthy device.
    """
    unavailable = {
        "available": False,
        "storage": "",
        "storage_model": "unknown",
        "config_mode": "unknown",
        "recovery_required": False,
        "recovery_reason": "",
        "active_revision_sha256": "",
        "total_bytes": 0,
        "used_bytes": 0,
        "estimated_free_bytes": 0,
        "deployment_enabled": False,
    }
    if payload is None:
        return unavailable
    if not isinstance(payload, dict) or payload.get("storage") != "littlefs":
        raise CapabilitiesError("Invalid v2 storage identifier")
    total = _quantity(payload, "total_bytes")
    used = _quantity(payload, "used_bytes")
    free = _quantity(payload, "estimated_free_bytes")
    if used > total or free > total - used:
        raise CapabilitiesError("Inconsistent LittleFS storage counters")
    model = payload.get("storage_model", "unknown")
    if model not in ("single-active", "unknown"):
        raise CapabilitiesError("Unsupported configuration storage model")
    mode = "unknown"
    recovery = False
    reason = ""
    active = ""
    if model == "single-active":
        mode = payload.get("config_mode")
        if mode not in ("legacy", "active", "recovery"):
            raise CapabilitiesError("Invalid active configuration mode")
        recovery = payload.get("recovery_required")
        if type(recovery) is not bool or recovery != (mode == "recovery"):
            raise CapabilitiesError("Inconsistent configuration recovery state")
        reason = payload.get("recovery_reason")
        if not isinstance(reason, str) or len(reason) > 120 or not all(
            char in _RECOVERY_CHARS for char in reason
        ):
            raise CapabilitiesError("Invalid recovery reason")
        active = _revision(
            payload.get("active_revision_sha256"), "selected active revision"
        )
        if mode == "active" and not active:
            raise CapabilitiesError("Active configuration has no revision")
        if mode == "legacy" and active:
            raise CapabilitiesError("Legacy mode cannot select a v2 revision")
    return {
        "available": True,
        "storage": "littlefs",
        "storage_model": model,
        "config_mode": mode,
        "recovery_required": recovery,
        "recovery_reason": reason,
        "active_revision_sha256": active,
        "total_bytes": total,
        "used_bytes": used,
        "estimated_free_bytes": free,
        "deployment_enabled": False,
    }
