"""Fail-closed PNG/JPEG dependency inventory for future complete OMOTE backups.

This is a *planning* and validation component, not an asset download API.
A JSON-only snapshot must never be represented as a full-device backup.
"""
from __future__ import annotations

from hashlib import sha256
import re
from typing import Mapping

from .single_active_manifest import referenced_images
from .workspace_model import WorkspaceError

MAX_ASSET_BYTES = 512 * 1024
MAX_TOTAL_ASSET_BYTES = 4 * 1024 * 1024
MAX_ASSETS = 64
_ALLOWED = re.compile(r"^Images/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:png|jpg|jpeg)$", re.I)


def inventory(files: dict[str, str], assets: Mapping[str, bytes] | None = None) -> dict:
    """Report referenced assets and whether *all* verified bytes are present.

    Only referenced images are accepted. Empty, oversized, unreferenced or
    path-traversal assets fail closed. This cannot validate image decoding:
    the firmware must verify the actual file format before activation.
    """
    references = referenced_images(files)
    if len(references) > MAX_ASSETS:
        raise WorkspaceError("Too many referenced image assets")
    if any(not _ALLOWED.fullmatch(path) or ".." in path.split("/") for path in references):
        raise WorkspaceError("Invalid image asset path")
    supplied = {} if assets is None else dict(assets)
    if set(supplied) - set(references):
        raise WorkspaceError("Unexpected or unreferenced image asset")
    total = 0
    entries = []
    for path in references:
        raw = supplied.get(path)
        if raw is None:
            entries.append({"path": path, "present": False, "length": 0, "sha256": ""})
            continue
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_ASSET_BYTES:
            raise WorkspaceError("Invalid image asset bytes or size")
        total += len(raw)
        if total > MAX_TOTAL_ASSET_BYTES:
            raise WorkspaceError("Image assets exceed total capacity")
        # Lightweight signatures are not full image decoders.
        if path.lower().endswith(".png") and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise WorkspaceError("PNG signature does not match asset extension")
        if path.lower().endswith((".jpg", ".jpeg")) and not raw.startswith(b"\xff\xd8\xff"):
            raise WorkspaceError("JPEG signature does not match asset extension")
        entries.append({"path": path, "present": True, "length": len(raw), "sha256": sha256(raw).hexdigest()})
    return {
        "referenced_count": len(references),
        "present_count": sum(int(x["present"]) for x in entries),
        "complete_assets": all(x["present"] for x in entries),
        "assets": entries,
        "total_asset_bytes": total,
        "remote_write_enabled": False,
    }
