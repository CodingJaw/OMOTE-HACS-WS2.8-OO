"""Admin-only OMOTE backup history inspection and HA-draft recovery.

No firmware writes, reboot or direct restoration to a remote occur here.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .backup_history import OmoteBackupHistory
from .const import DOMAIN
from .workspace_model import WorkspaceError

_REVISION = vol.All(vol.Coerce(int), vol.Range(min=0))
_INDEX = vol.All(vol.Coerce(int), vol.Range(min=0, max=2))
_HASH = vol.Match(r"^[0-9a-f]{64}$")
STORE_KEY = f"{DOMAIN}_workspace"


def _authorize(hass: HomeAssistant, connection, msg: dict) -> bool:
    if connection.user is None or not connection.user.is_admin:
        connection.send_error(
            msg["id"], websocket_api.ERR_UNAUTHORIZED, "Administrator required"
        )
        return False
    if msg["entry_id"] not in {
        item.entry_id for item in hass.config_entries.async_entries(DOMAIN)
    }:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown OMOTE remote"
        )
        return False
    return True


@websocket_api.websocket_command({
    vol.Required("type"): "omote_manager/backups/list",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_backup_list(hass: HomeAssistant, connection, msg: dict) -> None:
    """Return timestamps, sizes and integrity flags, never backup contents."""
    if not _authorize(hass, connection, msg):
        return
    try:
        history = await OmoteBackupHistory(hass, msg["entry_id"]).list_metadata()
    except WorkspaceError as exc:
        connection.send_error(
            msg["id"], websocket_api.ERR_INVALID_FORMAT, str(exc)
        )
        return
    connection.send_result(msg["id"], {
        "snapshots": history,
        "device_restored": False,
    })


@websocket_api.websocket_command({
    vol.Required("type"): "omote_manager/backups/load-to-draft",
    vol.Required("entry_id"): str,
    vol.Required("index"): _INDEX,
    vol.Required("sha256"): _HASH,
    vol.Required("revision"): _REVISION,
    vol.Optional("replace", default=False): bool,
})
@websocket_api.async_response
async def ws_backup_load_draft(hass: HomeAssistant, connection, msg: dict) -> None:
    """Replace only the selected Home Assistant local draft, with revision guard."""
    if not _authorize(hass, connection, msg):
        return
    try:
        files = await OmoteBackupHistory(hass, msg["entry_id"]).load_snapshot(
            msg["index"], msg["sha256"]
        )
        workspace = hass.data[STORE_KEY]
        await workspace.async_import(
            msg["revision"], msg["entry_id"], files, replace=msg["replace"]
        )
    except WorkspaceError as exc:
        connection.send_error(
            msg["id"], websocket_api.ERR_INVALID_FORMAT, str(exc)
        )
        return
    response = hass.data[STORE_KEY].summary()
    response["restored_to_local_draft_only"] = True
    response["device_restored"] = False
    connection.send_result(msg["id"], response)


def register_backup_websockets(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_backup_list)
    websocket_api.async_register_command(hass, ws_backup_load_draft)
