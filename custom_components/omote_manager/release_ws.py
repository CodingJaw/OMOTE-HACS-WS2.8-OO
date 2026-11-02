"""Admin-only HA review retention and offline ZIP download over WebSocket.

This module deliberately exposes no device configuration write methods. The
firmware's current /api/fs/write truncates live LittleFS files and has no
authentication, transactional commit, or guaranteed rollback.
"""
from __future__ import annotations

import base64
import hashlib
from functools import partial
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .api import OmoteApiError
from .const import DOMAIN
from .release_model import build_deployment_kit
from .review_model import apply_live_results
from .workspace_model import WorkspaceError
from .workspace_store import WorkspaceStore

STORE_KEY = f"{DOMAIN}_workspace"
_REVISION = vol.All(vol.Coerce(int), vol.Range(min=0))
_SHA256 = vol.Match(r"^[0-9a-f]{64}$")


def _admin(connection, msg: dict[str, Any]) -> bool:
    if connection.user is not None and connection.user.is_admin:
        return True
    connection.send_error(
        msg["id"], websocket_api.ERR_UNAUTHORIZED, "Administrator required"
    )
    return False


async def _remote_preflight(
    hass: HomeAssistant, entry_id: str, report: dict,
    originals: dict[str, str],
) -> dict:
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is None:
        raise OmoteApiError("Remote is not connected")
    # No POST, PUT, DELETE, device sync mode or reboot operations.
    await coordinator.api.status()
    inventory = set(await coordinator.api.files())
    contents = {}
    for item in report["changed_files"]:
        path = item["path"]
        if path in originals and path in inventory:
            contents[path] = await coordinator.api.read_file(
                path, verify_json=True
            )
    stale = (
        hass.data[STORE_KEY].summary()["revision"] != report["revision"]
    )
    return apply_live_results(report, inventory, contents, stale=stale)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/editor/export-kit",
        vol.Required("entry_id"): str,
        vol.Required("revision"): _REVISION,
        vol.Required("draft_sha256"): _SHA256,
        vol.Optional("check_live", default=True): bool,
    }
)
@websocket_api.async_response
async def ws_export_kit(hass: HomeAssistant, connection, msg: dict) -> None:
    """Package a validated, unchanged HA draft plus its imported baseline."""
    if not _admin(connection, msg):
        return
    store: WorkspaceStore = hass.data[STORE_KEY]
    try:
        report, proposed, baseline, originals = store.release_snapshot(
            msg["entry_id"]
        )
        if report["revision"] != msg["revision"]:
            raise WorkspaceError(
                "Workspace changed since review; rerun review before download"
            )
        if report["draft_sha256"] != msg["draft_sha256"]:
            raise WorkspaceError(
                "Draft hash changed since review; rerun review before download"
            )
        if report["errors"]:
            raise WorkspaceError("Fix validation errors before exporting a kit")
        if not report["changed_count"]:
            raise WorkspaceError("No changed configuration files to export")
        if msg["check_live"]:
            try:
                report = await _remote_preflight(
                    hass, msg["entry_id"], report, originals
                )
            except OmoteApiError:
                connection.send_error(
                    msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
                    "Live review failed; retry or choose offline export",
                )
                return
            if report["live_check"]["matches"] is not True:
                raise WorkspaceError(
                    "Remote conflicts or stale edits detected; review again"
                )
        if store.summary()["revision"] != msg["revision"]:
            raise WorkspaceError(
                "Workspace changed during export; review the new draft first"
            )
        zipbytes = await hass.async_add_executor_job(
            partial(
                build_deployment_kit,
                proposed, baseline, report,
                remote_id=msg["entry_id"]
            )
        )
        if store.summary()["revision"] != msg["revision"]:
            raise WorkspaceError(
                "Workspace changed while packaging; run review again"
            )
    except WorkspaceError as exc:
        connection.send_error(
            msg["id"], websocket_api.ERR_INVALID_FORMAT, str(exc)
        )
        return

    connection.send_result(msg["id"], {
        "filename": "omote-single-active-review.zip",
        "mime_type": "application/zip",
        "base64": base64.b64encode(zipbytes).decode("ascii"),
        "zip_sha256": hashlib.sha256(zipbytes).hexdigest(),
        "bytes": len(zipbytes),
        "draft_sha256": report["draft_sha256"],
        "review_status": (
            "remote_verified_at_export"
            if report["live_check"]["checked"] else "offline_unverified"
        ),
        "deployment_enabled": False,
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/editor/save-reviewed",
        vol.Required("entry_id"): str,
        vol.Required("revision"): _REVISION,
        vol.Required("draft_sha256"): _SHA256,
        vol.Optional("check_live", default=True): bool,
    }
)
@websocket_api.async_response
async def ws_save_reviewed(hass: HomeAssistant, connection, msg: dict) -> None:
    """Persist a reviewed snapshot in HA only, with a fresh optional drift check."""
    if not _admin(connection, msg):
        return
    store: WorkspaceStore = hass.data[STORE_KEY]
    try:
        report, _, _, originals = store.release_snapshot(msg["entry_id"])
        if report["revision"] != msg["revision"]:
            raise WorkspaceError("Workspace changed; run review again")
        if report["draft_sha256"] != msg["draft_sha256"]:
            raise WorkspaceError("Draft changed; run review again")
        if report["errors"]:
            raise WorkspaceError("Fix validation errors before retaining a review")
        if msg["check_live"]:
            try:
                report = await _remote_preflight(
                    hass, msg["entry_id"], report, originals
                )
            except OmoteApiError:
                connection.send_error(
                    msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
                    "Remote drift check failed; retry or choose offline review",
                )
                return
            if report["live_check"]["matches"] is not True:
                raise WorkspaceError("Remote drift or stale draft; run review again")
        metadata = await store.async_save_reviewed(
            msg["revision"], msg["entry_id"], msg["draft_sha256"],
            live_checked=bool(msg["check_live"] and report["changed_count"]),
        )
    except WorkspaceError as exc:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(exc))
        return
    response = store.summary()
    response["reviewed_saved"] = metadata
    response["deployment_enabled"] = False
    connection.send_result(msg["id"], response)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/editor/load-reviewed",
        vol.Required("entry_id"): str,
        vol.Required("revision"): _REVISION,
        vol.Required("reviewed_sha256"): _SHA256,
        vol.Optional("replace", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_load_reviewed(hass: HomeAssistant, connection, msg: dict) -> None:
    """Restore reviewed JSON to HA workspace only; no remote reads or writes."""
    if not _admin(connection, msg):
        return
    store: WorkspaceStore = hass.data[STORE_KEY]
    try:
        await store.async_load_reviewed_to_draft(
            msg["revision"], msg["entry_id"], msg["reviewed_sha256"],
            replace=msg["replace"],
        )
    except WorkspaceError as exc:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(exc))
        return
    response = store.summary()
    response["deployment_enabled"] = False
    connection.send_result(msg["id"], response)


def register_release_websockets(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_export_kit)
    websocket_api.async_register_command(hass, ws_save_reviewed)
    websocket_api.async_register_command(hass, ws_load_reviewed)
