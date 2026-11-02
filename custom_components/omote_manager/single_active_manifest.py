"""Exact-byte single-active *preview* manifest for safe OMOTE JSON drafts.

The firmware's canonical format is deterministic: {"format":...,"files":[...]}
with no insignificant whitespace and sorted file paths. This module creates
only a local preview, never an upload, NVS commit, or recovery operation.
Images and private device settings are NOT present in current HACS drafts.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .workspace_model import (
    WorkspaceError, check_bundle_limits, parse_jsonc, validate_bundle,
)

CANONICAL_FORMAT = "omote-config-generation-v1"
MAX_MANIFEST_BYTES = 32 * 1024
MAX_MANIFEST_FILES = 128
MAX_MANIFEST_TOTAL_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_FILE_BYTES = 256 * 1024


def referenced_images(files: dict[str, str]) -> list[str]:
    """Find image paths in known OMOTE Image widgets and nested JSON values."""
    refs: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if item.get("Type") == "Image":
                value = item.get("FileName")
                if not isinstance(value, str) or not value.startswith("Images/"):
                    refs.add("<invalid Image widget FileName>")
                else:
                    refs.add(value)
            for key, value in item.items():
                if key in ("FileName", "Image", "ImageFile", "ImagePath"):
                    if isinstance(value, str) and value.startswith("Images/"):
                        refs.add(value)
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    for path, raw in files.items():
        if path.endswith(".json"):
            walk(parse_jsonc(raw))
    return sorted(refs)


def build_canonical_json_manifest(
    files: dict[str, str],
) -> tuple[bytes, str]:
    """Produce firmware-compatible canonical bytes for complete JSON-only sets.

    Raise instead of creating a misleading manifest if an image is referenced,
    since this phase has no image download/digest/import support.
    """
    check_bundle_limits(files)
    errors = [item for item in validate_bundle(files)
              if item["level"] == "error"]
    if errors:
        raise WorkspaceError(
            f"Manifest preview blocked by {len(errors)} validation errors"
        )
    images = referenced_images(files)
    if images:
        raise WorkspaceError(
            "Image assets are not captured in Home Assistant drafts: " +
            ", ".join(images[:5]) +
            (" (additional images omitted)" if len(images) > 5 else "")
        )
    if len(files) > MAX_MANIFEST_FILES:
        raise WorkspaceError("Firmware manifest limit of 128 files exceeded")
    total = 0
    entries = []
    for path, body in sorted(files.items()):
        data = body.encode("utf-8")
        length = len(data)
        if not length or length > MAX_MANIFEST_FILE_BYTES:
            raise WorkspaceError(f"Unsupported firmware file size: {path}")
        total += length
        if total > MAX_MANIFEST_TOTAL_BYTES:
            raise WorkspaceError("Firmware manifest package exceeds 2 MiB")
        entries.append({
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "length": length,
        })
    manifest = {
        "format": CANONICAL_FORMAT,
        "files": entries,
    }
    raw = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(raw) > MAX_MANIFEST_BYTES:
        raise WorkspaceError("Canonical manifest exceeds firmware limit")
    return raw, hashlib.sha256(raw).hexdigest()


def preview_metadata(files: dict[str, str]) -> dict[str, Any]:
    """Return a JSON-safe readiness summary, without config content."""
    try:
        raw, digest = build_canonical_json_manifest(files)
    except WorkspaceError as exc:
        return {
            "complete_json_only": False,
            "manifest_sha256": "",
            "manifest_bytes": 0,
            "reason": str(exc)[:400],
            "deployment_enabled": False,
        }
    return {
        "complete_json_only": True,
        "manifest_sha256": digest,
        "manifest_bytes": len(raw),
        "reason": "JSON-only preview; no firmware activation or device write",
        "deployment_enabled": False,
    }
