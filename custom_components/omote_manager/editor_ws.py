"""Admin-only scene/page/button editor WebSocket API.

Every mutation changes only Home Assistant's persistent WorkspaceStore. These
commands never access the remote HTTP configuration write endpoints.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .workspace_model import WorkspaceError
from .workspace_store import WorkspaceStore

STORE_KEY = f"{DOMAIN}_workspace"
_POSITIVE_INT = vol.All(vol.Coerce(int), vol.Range(min=0))


def _admin(connection, msg: dict[str, Any]) -> bool:
    if connection.user is None or not connection.user.is_admin:
        connection.send_error(
            msg["id"], websocket_api.ERR_UNAUTHORIZED, "Administrator required"
        )
        return False
    return True


def _bad(connection, msg: dict, error: WorkspaceError) -> None:
    connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(error))


def _workspace(hass: HomeAssistant) -> WorkspaceStore:
    return hass.data[STORE_KEY]


def _result(hass: HomeAssistant, connection, msg: dict, **details) -> None:
    summary = _workspace(hass).summary()
    summary.update(details)
    connection.send_result(msg["id"], summary)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/editor/scene",
        vol.Required("entry_id"): str,
        vol.Required("path"): str,
    }
)
@websocket_api.async_response
async def ws_scene(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        detail = _workspace(hass).scene_editor(msg["entry_id"], msg["path"])
    except WorkspaceError as exc:
        _bad(connection, msg, exc)
        return
    connection.send_result(msg["id"], {
        "revision": _workspace(hass).summary()["revision"], "scene": detail
    })


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/editor/edit-scene",
        vol.Required("revision"): _POSITIVE_INT,
        vol.Required("entry_id"): str,
        vol.Required("path"): str,
        vol.Required("name"): str,
        vol.Required("screen_name"): str,
        vol.Required("bind_key"): str,
        vol.Required("press_type"): str,
    }
)
@websocket_api.async_response
async def ws_edit_scene(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        await _workspace(hass).async_edit_scene(
            msg["revision"], msg["entry_id"], msg["path"],
            msg["name"], msg["screen_name"], msg["bind_key"], msg["press_type"],
        )
    except WorkspaceError as exc:
        _bad(connection, msg, exc)
        return
    _result(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/editor/edit-page",
        vol.Required("revision"): _POSITIVE_INT,
        vol.Required("entry_id"): str,
        vol.Required("scene_path"): str,
        vol.Required("page_index"): _POSITIVE_INT,
        vol.Required("name"): str,
        vol.Required("short_name"): str,
    }
)
@websocket_api.async_response
async def ws_edit_page(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        await _workspace(hass).async_edit_page_title(
            msg["revision"], msg["entry_id"], msg["scene_path"],
            msg["page_index"], msg["name"], msg["short_name"],
        )
    except WorkspaceError as exc:
        _bad(connection, msg, exc)
        return
    _result(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/editor/edit-widget",
        vol.Required("revision"): _POSITIVE_INT,
        vol.Required("entry_id"): str,
        vol.Required("scene_path"): str,
        vol.Required("page_index"): _POSITIVE_INT,
        vol.Required("widget_index"): _POSITIVE_INT,
        vol.Required("field"): str,
        vol.Required("value"): str,
        vol.Optional("command_index", default=0): _POSITIVE_INT,
    }
)
@websocket_api.async_response
async def ws_edit_widget(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        await _workspace(hass).async_edit_widget(
            msg["revision"], msg["entry_id"], msg["scene_path"],
            msg["page_index"], msg["widget_index"],
            msg["field"], msg["value"], msg["command_index"],
        )
    except WorkspaceError as exc:
        _bad(connection, msg, exc)
        return
    _result(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/editor/edit-layout",
        vol.Required("revision"): _POSITIVE_INT,
        vol.Required("entry_id"): str,
        vol.Required("scene_path"): str,
        vol.Required("page_index"): _POSITIVE_INT,
        vol.Required("widget_index"): _POSITIVE_INT,
        vol.Required("settings"): vol.Schema(
            {
                vol.Required("mode"): vol.In(("flow", "align", "absolute")),
                vol.Required("align_to"): _POSITIVE_INT,
                vol.Required("x_pct"): _POSITIVE_INT,
                vol.Required("y_pct"): _POSITIVE_INT,
                vol.Optional("width_pct", default=None): vol.Any(None, _POSITIVE_INT),
                vol.Optional("height_pct", default=None): vol.Any(None, _POSITIVE_INT),
            }
        ),
    }
)
@websocket_api.async_response
async def ws_edit_layout(hass: HomeAssistant, connection, msg: dict) -> None:
    """Save a widget layout in HA-only draft storage."""
    if not _admin(connection, msg):
        return
    try:
        await _workspace(hass).async_edit_widget_layout(
            msg["revision"], msg["entry_id"], msg["scene_path"],
            msg["page_index"], msg["widget_index"], msg["settings"],
        )
    except WorkspaceError as exc:
        _bad(connection, msg, exc)
        return
    _result(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/editor/edit-button",
        vol.Required("revision"): _POSITIVE_INT,
        vol.Required("entry_id"): str,
        vol.Required("scene_path"): str,
        vol.Required("page_index"): _POSITIVE_INT,
        vol.Required("key"): str,
        vol.Required("event"): str,
        vol.Required("command"): str,
    }
)
@websocket_api.async_response
async def ws_edit_button(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        await _workspace(hass).async_edit_button_map(
            msg["revision"], msg["entry_id"], msg["scene_path"],
            msg["page_index"], msg["key"], msg["event"], msg["command"],
        )
    except WorkspaceError as exc:
        _bad(connection, msg, exc)
        return
    _result(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/editor/diff",
        vol.Required("entry_id"): str,
        vol.Optional("path"): str,
    }
)
@websocket_api.async_response
async def ws_diff(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        response = _workspace(hass).diff(msg["entry_id"], msg.get("path"))
    except WorkspaceError as exc:
        _bad(connection, msg, exc)
        return
    connection.send_result(msg["id"], response)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "omote_manager/editor/revert",
        vol.Required("revision"): _POSITIVE_INT,
        vol.Required("entry_id"): str,
        vol.Required("path"): str,
    }
)
@websocket_api.async_response
async def ws_revert(hass: HomeAssistant, connection, msg: dict) -> None:
    if not _admin(connection, msg):
        return
    try:
        await _workspace(hass).async_revert_file(
            msg["revision"], msg["entry_id"], msg["path"]
        )
    except WorkspaceError as exc:
        _bad(connection, msg, exc)
        return
    _result(hass, connection, msg)


def register_editor_websockets(hass: HomeAssistant) -> None:
    """Register all editor commands using HA Core 2024.9 WebSocket APIs."""
    for handler in (
        ws_scene, ws_edit_scene, ws_edit_page, ws_edit_widget,
        ws_edit_button, ws_edit_layout, ws_diff, ws_revert,
    ):
        websocket_api.async_register_command(hass, handler)
