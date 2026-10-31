"""Admin-only websocket endpoints for OMOTE's non-deployed HA workspace.

All mutation endpoints change only Home Assistant private storage.
No command in this module sends a POST or PUT request to firmware.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .api import OmoteApiError
from .const import DOMAIN
from .safe_files import is_exportable_json
from .workspace_model import (
    MAX_FILES,
    MAX_TOTAL_BYTES,
    WorkspaceError,
)
from .workspace_store import WorkspaceStore
from .editor_ws import register_editor_websockets

_LOGGER = logging.getLogger(__name__)
STORE_KEY = f"{DOMAIN}_workspace"
_REVISION = vol.All(vol.Coerce(int), vol.Range(min=0))


def _admin(connection, msg: dict[str, Any]) -> bool:
    if connection.user is None or not connection.user.is_admin:
        connection.send_error(
            msg["id"], websocket_api.ERR_UNAUTHORIZED, "Administrator required"
        )
        return False
    return True


def _workspace(hass: HomeAssistant) -> WorkspaceStore:
    return hass.data[STORE_KEY]


def _bad_input(connection, msg: dict, error: WorkspaceError) -> None:
    connection.send_error(
        msg["id"], websocket_api.ERR_INVALID_FORMAT, str(error)
    )


def _result(hass: HomeAssistant, connection, msg: dict,
            details: dict | None = None) -> None:
    result = _workspace(hass).summary()
    if details:
        result.update(details)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {vol.Required("type"): "omote_manager/workspace"}
)
@websocket_api.async_response
async def ws_workspace(hass: HomeAssistant, connection, msg: dict) -> None:
    if _admin(connection, msg):
        _result(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/workspace/import",
        vol.Required("entry_id"): str,
        vol.Required("revision"): _REVISION,
        vol.Optional("replace", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_import(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    coordinator = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    if coordinator is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Remote not connected"
        )
        return
    try:
        await coordinator.api.status()
        inventory = await coordinator.api.files()
        paths = sorted({path for path in inventory if is_exportable_json(path)})
        if not paths or len(paths) > MAX_FILES:
            raise WorkspaceError("Invalid or oversized configuration inventory")
        files = {}
        total = 0
        for path in paths:
            text = await coordinator.api.read_file(path, verify_json=True)
            total += len(text.encode("utf-8"))
            if total > MAX_TOTAL_BYTES:
                raise WorkspaceError("Import exceeds 512 KiB limit")
            files[path] = text
        await _workspace(hass).async_import(
            msg["revision"],
            msg["entry_id"],
            files,
            replace=msg["replace"],
        )
    except WorkspaceError as exc:
        _bad_input(connection, msg, exc)
        return
    except OmoteApiError as exc:
        _LOGGER.warning("OMOTE draft import failed: %s", exc)
        connection.send_error(
            msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
            f"Import aborted; saved draft unchanged. {str(exc)[:380]}"
        )
        return
    _result(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/workspace/location",
        vol.Required("revision"): _REVISION,
        vol.Required("name"): str,
        vol.Optional("parent_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_location(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        new_id = await _workspace(hass).async_create_location(
            msg["revision"], msg["name"], msg.get("parent_id")
        )
    except WorkspaceError as exc:
        _bad_input(connection, msg, exc)
        return
    _result(hass, connection, msg, {"new_id": new_id})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/workspace/template",
        vol.Required("revision"): _REVISION,
        vol.Required("entry_id"): str,
        vol.Required("scene_path"): str,
        vol.Required("name"): str,
        vol.Optional("location_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_template(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        new_id = await _workspace(hass).async_create_template(
            msg["revision"],
            msg["entry_id"],
            msg["scene_path"],
            msg["name"],
            msg.get("location_id"),
        )
    except WorkspaceError as exc:
        _bad_input(connection, msg, exc)
        return
    _result(hass, connection, msg, {"new_id": new_id})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/workspace/apply-template",
        vol.Required("revision"): _REVISION,
        vol.Required("entry_id"): str,
        vol.Required("template_id"): str,
    }
)
@websocket_api.async_response
async def ws_apply_template(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        await _workspace(hass).async_apply_template(
            msg["revision"], msg["entry_id"], msg["template_id"]
        )
    except WorkspaceError as exc:
        _bad_input(connection, msg, exc)
        return
    _result(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/workspace/commands",
        vol.Required("entry_id"): str,
        vol.Required("path"): str,
    }
)
@websocket_api.async_response
async def ws_commands(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        commands = _workspace(hass).commands(msg["entry_id"], msg["path"])
    except WorkspaceError as exc:
        _bad_input(connection, msg, exc)
        return
    connection.send_result(
        msg["id"],
        {
            "revision": _workspace(hass).summary()["revision"],
            "commands": commands,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/workspace/edit-command",
        vol.Required("revision"): _REVISION,
        vol.Required("entry_id"): str,
        vol.Required("path"): str,
        vol.Required("name"): str,
        vol.Required("mode"): str,
        vol.Required("protocol"): str,
        vol.Required("data"): [str],
    }
)
@websocket_api.async_response
async def ws_edit_command(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        await _workspace(hass).async_edit_command(
            msg["revision"],
            msg["entry_id"],
            msg["path"],
            msg["name"],
            msg["mode"],
            msg["protocol"],
            msg["data"],
        )
    except WorkspaceError as exc:
        _bad_input(connection, msg, exc)
        return
    _result(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/workspace/validate",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_validate(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        result = _workspace(hass).validation(msg["entry_id"])
    except WorkspaceError as exc:
        _bad_input(connection, msg, exc)
        return
    connection.send_result(msg["id"], result)


def register_workspace_websockets(hass: HomeAssistant) -> None:
    """Register endpoints supported by HA Core 2024.9.1."""
    for handler in (
        ws_workspace,
        ws_import,
        ws_location,
        ws_template,
        ws_apply_template,
        ws_commands,
        ws_edit_command,
        ws_validate,
    ):
        websocket_api.async_register_command(hass, handler)
    register_editor_websockets(hass)
