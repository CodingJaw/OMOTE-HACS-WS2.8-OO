"""Read-only deployment review manifest for local OMOTE drafts.

This module never calls the firmware or changes a draft. Actual deployment is
disabled until the firmware has authenticated transactional writes and rollback.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .workspace_model import (
    WorkspaceError, check_bundle_limits, file_digest, validate_bundle,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_review(draft: dict[str, str], imported: dict[str, str]) -> dict[str, Any]:
    """Build a bounded, credential-excluding change manifest.

    Only locally-imported safe paths are accepted; never include file content
    in the response. The file hash is over raw UTF-8 bytes, not parsed JSON.
    """
    check_bundle_limits(draft)
    check_bundle_limits(imported)
    changed = []
    for path in sorted(draft.keys() | imported.keys()):
        before = imported.get(path)
        after = draft.get(path)
        if before == after:
            continue
        changed.append({
            "path": path,
            "operation": "add" if before is None else (
                "delete" if after is None else "modify"
            ),
            "before_sha256": _sha256(before) if before is not None else None,
            "after_sha256": _sha256(after) if after is not None else None,
            "before_bytes": len(before.encode("utf-8")) if before is not None else 0,
            "after_bytes": len(after.encode("utf-8")) if after is not None else 0,
        })

    issues = validate_bundle(draft)
    errors = sum(issue["level"] == "error" for issue in issues)
    warnings = sum(issue["level"] == "warning" for issue in issues)
    reasons: list[str] = []
    if not changed:
        reasons.append("No draft changes to review")
    if errors:
        reasons.append(f"Draft validation has {errors} error(s)")
    reasons.append(
        "Firmware deployment remains disabled until authenticated, "
        "single-active transactions and independent recovery are hardware-tested"
    )
    return {
        "changed_files": changed,
        "changed_count": len(changed),
        "baseline_sha256": file_digest(imported),
        "draft_sha256": file_digest(draft),
        "errors": errors,
        "warnings": warnings,
        "issues": issues[:100],
        "validation_truncated": len(issues) > 100,
        "blockers": reasons,
        "deployment_enabled": False,
        "live_check": {
            "checked": False,
            "matches": None,
            "checked_files": 0,
            "conflicts": [],
            "note": "Optional live drift check covers files changed by this draft only",
        },
    }


def apply_live_results(
    report: dict[str, Any],
    inventory: set[str],
    live_contents: dict[str, str],
    *,
    stale: bool = False,
) -> dict[str, Any]:
    """Compare a preflight snapshot to remote files without writing anything.

    Existing modified/deleted paths must exactly match the imported source.
    New files must not unexpectedly already exist on the device.
    """
    if report["live_check"]["checked"]:
        raise WorkspaceError("Live check already completed")
    conflicts: list[dict[str, str]] = []
    checked = 0
    for change in report["changed_files"]:
        path = change["path"]
        source_hash = change["before_sha256"]
        if source_hash is None:
            if path in inventory:
                conflicts.append({
                    "path": path,
                    "reason": "New draft file already exists on remote",
                })
            continue
        if path not in inventory:
            conflicts.append({
                "path": path,
                "reason": "Imported original file is now missing on remote",
            })
            continue
        raw = live_contents.get(path)
        if raw is None:
            conflicts.append({
                "path": path,
                "reason": "Live file was not read for comparison",
            })
            continue
        checked += 1
        if _sha256(raw) != source_hash:
            conflicts.append({
                "path": path,
                "reason": "Remote file changed since draft import (hash mismatch)",
            })
    if stale:
        conflicts.append({
            "path": "",
            "reason": "Workspace changed during the live check; run it again",
        })
    updated = dict(report)
    updated["live_check"] = {
        "checked": True,
        "matches": not conflicts,
        "checked_files": checked,
        "conflicts": conflicts,
        "note": "Read-only point-in-time check; changes after the check remain possible",
    }
    updated["blockers"] = list(report["blockers"])
    if conflicts:
        updated["blockers"].insert(
            0, f"Detected {len(conflicts)} live-drift or review-conflict issue(s)"
        )
    return updated
