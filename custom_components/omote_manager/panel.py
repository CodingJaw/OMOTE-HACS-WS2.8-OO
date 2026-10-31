"""Sidebar panel and admin-only read-only websocket API for OMOTE Manager.

Compatible with Home Assistant 2024.9.1:
- panel_custom.async_register_panel(..., module_url=...)
- hass.http.async_register_static_paths([StaticPathConfig(...)])
- websocket_api.websocket_command / async_response
"""
from __future__ import annotations

from pathlib import Path

import voluptuous as vol

from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .api import OmoteApiError
from .const import DOMAIN
from .safe_files import is_exportable_json
from .workspace_ws import register_workspace_websockets

PANEL_PATH = "omote-manager"
PANEL_ELEMENT = "omote-manager-panel-v9"
STATIC_PATH = "/omote_manager_static"
ASSET_VERSION = "0.1.0-dev9"


async def async_register_manager_panel(hass: HomeAssistant) -> None:
    """Register a management sidebar panel and its authenticated data calls."""
    static_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_PATH, str(static_dir), False)]
    )
    websocket_api.async_register_command(hass, websocket_overview)
    websocket_api.async_register_command(hass, websocket_file)
    register_workspace_websockets(hass)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        module_url=f"{STATIC_PATH}/omote-panel.js?v={ASSET_VERSION}",
        sidebar_title="OMOTE Manager",
        sidebar_icon="mdi:remote",
        require_admin=True,
        config_panel_domain=DOMAIN,
    )


def _admin_only(connection, msg: dict) -> bool:
    """Verify admin permission even for direct websocket callers."""
    if connection.user is None or not connection.user.is_admin:
        connection.send_error(
            msg["id"], websocket_api.ERR_UNAUTHORIZED, "Administrator required"
        )
        return False
    return True


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/overview",
        vol.Optional("refresh", default=False): bool,
    }
)
@websocket_api.async_response
async def websocket_overview(hass: HomeAssistant, connection, msg: dict) -> None:
    """List registered remotes and available nonsensitive JSON paths."""
    if not _admin_only(connection, msg):
        return

    remotes = []
    coordinators = hass.data.get(DOMAIN, {})
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = coordinators.get(entry.entry_id)
        if msg.get("refresh") and coordinator is not None:
            await coordinator.async_request_refresh()

        data = (coordinator.data or {}) if coordinator else {}
        status = data.get("status", {})
        all_files = data.get("files", [])
        safe_files = sorted(path for path in all_files if is_exportable_json(path))
        remotes.append(
            {
                "entry_id": entry.entry_id,
                "name": entry.title,
                "host": entry.data.get("host"),
                "port": entry.data.get("port", 80),
                "online": bool(
                    coordinator is not None and coordinator.last_update_success
                ),
                "api": status.get("api", "") if isinstance(status, dict) else "",
                "files": safe_files,
                "total_files": len(all_files),
            }
        )
    connection.send_result(
        msg["id"],
        {
            "remotes": remotes,
            "read_only": True,
            "version": ASSET_VERSION,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/file",
        vol.Required("entry_id"): str,
        vol.Required("path"): str,
    }
)
@websocket_api.async_response
async def websocket_file(hass: HomeAssistant, connection, msg: dict) -> None:
    """Read one allowed JSON file on a registered remote."""
    if not _admin_only(connection, msg):
        return
    coordinator = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    if coordinator is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "OMOTE remote is not loaded"
        )
        return
    path = msg["path"]
    if not is_exportable_json(path):
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_ALLOWED, "File is not accessible"
        )
        return
    available_files = (coordinator.data or {}).get("files", [])
    if path not in available_files:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "File is not in the inventory"
        )
        return
    try:
        content = await coordinator.api.read_file(path)
    except OmoteApiError:
        connection.send_error(
            msg["id"], websocket_api.ERR_UNKNOWN_ERROR, "Cannot read remote file"
        )
        return
    connection.send_result(msg["id"], {"path": path, "content": content})
