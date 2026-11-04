"""Admin-only, read-only image diagnostics for one registered OMOTE remote."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .api import OmoteApiError
from .asset_diagnostics import inspect_remote_images
from .const import DOMAIN
from .workspace_model import WorkspaceError

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command({
    vol.Required("type"): "omote_manager/assets/diagnose",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_asset_diagnostics(
    hass: HomeAssistant, connection, msg: dict
) -> None:
    """Inspect public images; never mutate firmware or HA drafts."""
    if connection.user is None or not connection.user.is_admin:
        connection.send_error(
            msg["id"], websocket_api.ERR_UNAUTHORIZED, "Administrator required"
        )
        return
    if msg["entry_id"] not in {
        entry.entry_id for entry in hass.config_entries.async_entries(DOMAIN)
    }:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown OMOTE remote"
        )
        return
    coordinator = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    if coordinator is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Remote not connected"
        )
        return
    try:
        report = await inspect_remote_images(coordinator.api)
    except (OmoteApiError, WorkspaceError) as exc:
        _LOGGER.warning("OMOTE image diagnostic aborted: %s", exc)
        connection.send_error(
            msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
            "Image scan aborted: " + str(exc)[:280],
        )
        return
    connection.send_result(msg["id"], report)


def register_asset_websockets(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_asset_diagnostics)
