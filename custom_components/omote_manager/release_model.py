"""Build a single-active reviewed configuration and imported-baseline ZIP.

The archive deliberately contains two *separate full JSON snapshots*, not a
flashable image or an auto-install script. This allows a human to inspect the
draft and retain the last imported configuration as a recovery reference.

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
from .workspace_model import WorkspaceError, check_bundle_limits, file_digest
from .portable_manifest import make_portable_index

BUNDLE_VERSION = "omote-manager-single-active-review-v2"
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
_WARNING = (
    "OFFLINE REVIEW ONLY. NOT A FIRMWARE IMAGE OR A DEPLOYMENT PACKAGE.\n\n"
    "proposed/ contains the locally reviewed Home Assistant JSON draft.\n"
    "imported-baseline/ contains the JSON imported from the remote before edits.\n"
    "PORTABLE_INDEX.json contains per-file SHA-256 and exact byte lengths.\n\n"
    "OMOTE uses ONE active configuration; there is no A/B configuration or\n"
    "automatic rollback. Home Assistant may eventually resend a reviewed copy\n"
    "only through a future authenticated, touchscreen-approved transaction API.\n"
    "No firmware writes or recovery operations are included in this ZIP.\n\n"
    "Wi-Fi/NVS credentials, device-specific private settings, image assets and\n"
    "other non-JSON files are EXCLUDED. This is not a complete device backup or\n"
    "a firmware-ready manifest. User JSON can contain sensitive command data.\n"
    "Protect this archive and retain your verified full-flash backup separately.\n"
    "A remote drift check is only a point-in-time comparison.\n"
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
    """Create a JSON-only proposal + imported-baseline ZIP from HA snapshots.

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
    manifest = {
        "format": BUNDLE_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "entry_id": remote_id,
        "deployable_by_current_integration": False,
        "storage_model": "single-active",
        "automatic_rollback": False,
        "firmware_api": "read-only-v1-or-v2-preview",
        "review_status": "remote_verified_at_export" if verified else "offline_unverified",
        "remote_check_performed": bool(live.get("checked")),
        "remote_check_is_point_in_time": True,
        "draft_sha256": expected["draft_sha256"],
        "baseline_sha256": expected["baseline_sha256"],
        "changed_files": expected["changed_files"],
        "changes": expected["changed_count"],
        "proposed_file_count": len(proposed),
        "imported_baseline_file_count": len(baseline),
        "complete_for_firmware_deployment": False,
        "portable_index_file": "PORTABLE_INDEX.json",
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
        _append(
            archive, "PORTABLE_INDEX.json",
            json.dumps(make_portable_index(proposed), sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False) + "\n",
        )
        for prefix, files in (("proposed", proposed), ("imported-baseline", baseline)):
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
