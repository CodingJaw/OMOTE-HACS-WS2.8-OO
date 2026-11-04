"""Read-only on-demand PNG/JPEG diagnostic for an attached OMOTE remote.

This does NOT create an image backup, expose binary data over Home Assistant
WebSockets, permit a firmware write, or prove atomic firmware snapshots.
"""
from __future__ import annotations

from hashlib import sha256

from .api import OmoteApiError
from .asset_inventory import MAX_ASSETS, MAX_TOTAL_ASSET_BYTES, _ALLOWED
from .safe_files import is_exportable_json
from .single_active_manifest import referenced_images
from .workspace_model import (
    MAX_FILES, WorkspaceError, check_bundle_limits, parse_jsonc,
)


def _safe_image(path: object) -> bool:
    return (
        isinstance(path, str)
        and len(path) <= 240
        and _ALLOWED.fullmatch(path) is not None
        and ".." not in path
        and "\\" not in path
    )


async def inspect_remote_images(api) -> dict:
    """Inspect only public files and return metadata, never file contents.

    Analyze fresh, live remote JSON rather than an edited HA draft. Individual
    transfer failures remain visible per image; a failed check is never marked
    verified. Bounded by existing JSON, per-image and total-image quotas.
    """
    await api.status()
    tree = await api.files()
    public_json = sorted(set(p for p in tree if is_exportable_json(p)))
    if not public_json or len(public_json) > MAX_FILES or "Scenes.json" not in public_json:
        raise WorkspaceError("Remote JSON inventory is missing or exceeds safe limits")
    files: dict[str, str] = {}
    for path in public_json:
        body = await api.read_file(path, verify_json=True)
        files[path] = body
        check_bundle_limits(files)
        # Avoid treating malformed content as image-free.
        parse_jsonc(body)

    references = referenced_images(files)
    on_device = set(tree)
    discovered = {p for p in on_device if _safe_image(p)}
    candidates = sorted(set(references) | discovered)
    if len(candidates) > MAX_ASSETS:
        raise WorkspaceError("More than 64 image paths; scan blocked by safety quota")

    result = []
    total = 0
    for path in candidates:
        row = {
            "path": path[:240], "referenced": path in references,
            "present": path in on_device, "verified": False,
            "bytes": 0, "sha256": "", "error": "",
        }
        if not _safe_image(path):
            row["error"] = "Invalid or unsupported image reference"
        elif path not in on_device:
            row["error"] = "Referenced image missing from device inventory"
        elif total >= MAX_TOTAL_ASSET_BYTES:
            row["error"] = "Total 4 MiB diagnostic quota exceeded"
        else:
            try:
                # Enforces max 512 KiB, raw/chunk completeness, magic signature,
                # and post-read file size. No binary data leaves the backend.
                raw = await api.read_image_asset(path)
                if total + len(raw) > MAX_TOTAL_ASSET_BYTES:
                    row["error"] = "Total 4 MiB diagnostic quota exceeded"
                else:
                    total += len(raw)
                    row["bytes"] = len(raw)
                    row["sha256"] = sha256(raw).hexdigest()
                    row["verified"] = True
            except OmoteApiError as exc:
                row["error"] = str(exc)[:200]
        result.append(row)
    missing = sum(bool(row["referenced"] and not row["verified"]) for row in result)
    failed = sum(bool(not row["verified"]) for row in result)
    return {
        "json_file_count": len(files),
        "referenced_count": len(references),
        "discovered_count": len(discovered),
        "checked_count": len(result),
        "verified_count": sum(bool(row["verified"]) for row in result),
        "failed_count": failed,
        "unverified_references": missing,
        "total_bytes": total,
        "complete_references": missing == 0,
        "assets": result,
        "read_only": True,
        "complete_backup": False,
        "deployment_enabled": False,
        "note": ("No PNG/JPEG files or references found; image retrieval NOT TESTED."
                 if not result else
                 "SHA-256 verifies received bytes only; no atomic snapshot or image backup."),
    }
