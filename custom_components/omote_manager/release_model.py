"""Build a portable single-active review kit without writing to OMOTE.

The archive deliberately contains two *separate full JSON snapshots*, not a
flashable image or an auto-install script. This allows a human to inspect the
draft and retain the originally imported baseline as a local reference.

Only an administrator with an existing Home Assistant integration session can
request the archive. No credentials from DeviceSettings/HaSettings are included.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import PurePosixPath
import zipfile
from typing import Any

from .review_model import make_review
from .single_active_manifest import build_canonical_json_manifest, referenced_images
from .workspace_model import WorkspaceError, check_bundle_limits, file_digest

BUNDLE_VERSION = "omote-manager-single-active-review-kit-v2"
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
_WARNING = (
    "THIS ARCHIVE IS NOT FIRMWARE, NOT AN INSTALLER, AND CANNOT BE DEPLOYED.\n\n"
    "proposed/ contains a reviewed HA JSON draft; baseline/ contains the\n"
    "original imported JSON from that remote. baseline/ is NOT a device-side\n"
    "automatic rollback generation and does not imply restore support.\n\n"
    "When no image assets are referenced, GENERATION_MANIFEST_PREVIEW.json\n"
    "contains exact canonical JSON manifest bytes for comparison with the\n"
    "future firmware API. The manifest is NEVER sufficient for a safe deploy\n"
    "without authenticated transport, device approval and hardware testing.\n"
    "Any referenced images prevent canonical-manifest generation because\n"
    "HACS currently stores safe JSON only, not image file bytes.\n\n"
    "Private DeviceSettings/HaSettings and network/pairing credentials are\n"
    "EXCLUDED. Custom JSON can still be sensitive; protect this ZIP.\n"
    "A live remote-drift check is point-in-time and covers changed files,\n"
    "not a proof that configuration is presently installed or complete.\n"
    "To recover a broken device, use the firmware's independent recovery UI\n"
    "and a separately reviewed secure re-send AFTER that API is implemented.\n"
)



def _zip_entry(path: str, data: bytes) -> zipfile.ZipInfo:
    """Deterministic ZIP metadata and no host file permissions."""
    entry = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = 0o100644 << 16
    entry.create_system = 3
    return entry


def _append(archive: zipfile.ZipFile, name: str, text: str) -> None:
    archive.writestr(_zip_entry(name, text.encode("utf-8")), text.encode("utf-8"))


def build_deployment_kit(
    proposed: dict[str, str],
    baseline: dict[str, str],
    report: dict[str, Any],
    *,
    remote_id: str,
) -> bytes:
    """Create a portable proposal + rollback ZIP from immutable HA snapshots.

    If the validation, hash, or live-drift review is stale or conflicted, raise
    WorkspaceError rather than returning a potentially misleading bundle.
    """
    check_bundle_limits(proposed)
    check_bundle_limits(baseline)
    if not isinstance(remote_id, str) or not remote_id or len(remote_id) > 128:
        raise WorkspaceError("Invalid remote entry ID")
    expected = make_review(proposed, baseline)
    if expected["draft_sha256"] != report.get("draft_sha256"):
        raise WorkspaceError("Draft changed since review; run preflight again")
    if expected["baseline_sha256"] != report.get("baseline_sha256"):
        raise WorkspaceError("Imported baseline changed; run preflight again")
    if expected["changed_files"] != report.get("changed_files"):
        raise WorkspaceError("Change manifest changed since review")
    if expected["errors"]:
        raise WorkspaceError(
            f"Cannot export a release kit with {expected['errors']} validation error(s)"
        )
    if not expected["changed_count"]:
        raise WorkspaceError("There are no draft changes to include in a release kit")
    live = report.get("live_check", {})
    if live.get("checked") and not live.get("matches"):
        raise WorkspaceError("The remote has conflicting changes; archive export blocked")

    verified = bool(live.get("checked") and live.get("matches"))
    unresolved_images = referenced_images(proposed)
    canonical = None
    canonical_sha256 = ""
    if not unresolved_images:
        canonical, canonical_sha256 = build_canonical_json_manifest(proposed)
    manifest = {
        "format": BUNDLE_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "entry_id": remote_id,
        "deployable_by_current_integration": False,
        "firmware_api": "omote-config-v2-preview",
        "storage_model": "single-active",
        "automatic_rollback_supported": False,
        "remote_write_enabled": False,
        "canonical_manifest_included": canonical is not None,
        "canonical_manifest_sha256": canonical_sha256,
        "referenced_assets_not_included": unresolved_images,
        "review_status": "remote_verified_at_export" if verified else "offline_unverified",
        "remote_check_performed": bool(live.get("checked")),
        "remote_check_is_point_in_time": True,
        "draft_sha256": expected["draft_sha256"],
        "baseline_sha256": expected["baseline_sha256"],
        "changed_files": expected["changed_files"],
        "changes": expected["changed_count"],
        "proposed_file_count": len(proposed),
        "baseline_file_count": len(baseline),
        "secrets_and_non_json_assets_excluded": True,
        "instructions_file": "READ_ME_FIRST.txt",
    }
    json_manifest = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    buffer = BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_DEFLATED,
        compresslevel=6, allowZip64=False,
    ) as archive:
        _append(archive, "READ_ME_FIRST.txt", _WARNING)
        _append(archive, "MANIFEST.json", json_manifest)
        if canonical is not None:
            archive.writestr(
                _zip_entry("GENERATION_MANIFEST_PREVIEW.json", canonical),
                canonical,
            )
        for prefix, files in (("proposed", proposed), ("baseline", baseline)):
            for path, body in sorted(files.items()):
                # check_bundle_limits has vetted all firmware paths. Do not
                # create ZIP entries from arbitrary user-provided absolute paths.
                if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
                    raise WorkspaceError("Unsafe archive path")
                _append(archive, f"{prefix}/{path}", body)
    result = buffer.getvalue()
    if len(result) > MAX_BUNDLE_BYTES:
        raise WorkspaceError("Deployment kit exceeds the download size limit")
    return result
