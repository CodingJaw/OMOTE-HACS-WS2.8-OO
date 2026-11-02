"""Deterministic JSON-only manifest for offline OMOTE review packages.

This is NOT the firmware's canonical active-manifest wire format. Image assets,
device-specific settings and authentication are intentionally absent. Never
interpret a matching SHA-256 as permission to deploy or activate a revision.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .workspace_model import (
    WorkspaceError, check_bundle_limits, file_digest, validate_bundle,
)


def make_portable_index(files: dict[str, str]) -> dict[str, Any]:
    """Return sorted exact-byte SHA-256 entries for a validated JSON subset."""
    check_bundle_limits(files)
    if "Scenes.json" not in files:
        raise WorkspaceError("Portable index requires Scenes.json")
    errors = [item for item in validate_bundle(files) if item["level"] == "error"]
    if errors:
        raise WorkspaceError(
            f"Portable index cannot include {len(errors)} invalid configuration reference(s)"
        )
    entries = []
    for path in sorted(files):
        body = files[path].encode("utf-8")
        entries.append({
            "path": path,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
    return {
        "format": "omote-portable-json-index-v1",
        "storage_model": "single-active",
        "bundle_sha256": file_digest(files),
        "file_count": len(entries),
        "total_bytes": sum(item["bytes"] for item in entries),
        "files": entries,
        "image_assets_included": False,
        "private_settings_included": False,
        "complete_for_firmware_deployment": False,
        "deployment_enabled": False,
    }
