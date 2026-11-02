"""Administrator-only reviewed configuration retention and local draft loading.

These actions are Home Assistant .storage operations. There are no firmware
POST/PUT/DELETE methods, no pairing shortcut, and no automatic recovery push.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .workspace_model import WorkspaceError

STORE_KEY = f"{DOMAIN}_workspace"
_REVISION = vol.All(vol.Coerce(int), vol.Range(min=0))
_SHA256 = vol.Match(r"^[0-9a-f]{64}$")


def _authorize(hass: HomeAssistant, connection, msg: dict) -> bool:
    if connection.user is None or not connection.user.is_admin:
        connection.send_error(
            msg["id"], websocket_api.ERR_UNAUTHORIZED, "Administrator required"
        )
        return False
    if msg["entry_id"] not in {
        entry.entry_id for entry in hass.config_entries.async_entries(DOMAIN)
    }:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown OMOTE remote"
        )
        return False
    return True


@websocket_api.websocket_command({
    vol.Required("type"): "omote_manager/reviewed/retain",
    vol.Required("entry_id"): str,
    vol.Required("revision"): _REVISION,
    vol.Required("draft_sha256"): _SHA256,
})
@websocket_api.async_response
async def ws_retain(hass: HomeAssistant, connection, msg: dict) -> None:
    """Explicitly retain validated draft bytes in independent HA storage."""
    if not _authorize(hass, connection, msg):
        return
    store = hass.data[STORE_KEY]
    try:
        await store.async_retain_reviewed(
            msg["revision"], msg["entry_id"], msg["draft_sha256"]
        )
    except WorkspaceError as exc:
        connection.send_error(
            msg["id"], websocket_api.ERR_INVALID_FORMAT, str(exc)
        )
        return
    connection.send_result(msg["id"], store.summary())


@websocket_api.websocket_command({
    vol.Required("type"): "omote_manager/reviewed/load-to-draft",
    vol.Required("entry_id"): str,
    vol.Required("revision"): _REVISION,
    vol.Required("sha256"): _SHA256,
    vol.Optional("replace", default=False): bool,
})
@websocket_api.async_response
async def ws_load_reviewed(hass: HomeAssistant, connection, msg: dict) -> None:
    """Restore retained bytes into HA draft only, with explicit replace."""
    if not _authorize(hass, connection, msg):
        return
    store = hass.data[STORE_KEY]
    try:
        await store.async_load_reviewed(
            msg["revision"], msg["entry_id"], msg["sha256"],
            replace=msg["replace"],
        )
    except WorkspaceError as exc:
        connection.send_error(
            msg["id"], websocket_api.ERR_INVALID_FORMAT, str(exc)
        )
        return
    result = store.summary()
    result["restored_to_local_draft_only"] = True
    result["device_restored"] = False
    connection.send_result(msg["id"], result)


def register_reviewed_websockets(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_retain)
    websocket_api.async_register_command(hass, ws_load_reviewed)
