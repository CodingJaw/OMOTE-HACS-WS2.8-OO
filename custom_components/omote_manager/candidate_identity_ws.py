"""Admin-only local HA candidate key endpoints, NOT firmware pairing.

No PIN entry, no Security2 socket, no fingerprint trust enrollment, no
device writes, no secret serialization into WebSocket responses.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .candidate_identity import CandidateIdentityError
from .const import DOMAIN

IDENTITY_STORE_KEY = f"{DOMAIN}_candidate_identity_store"


def _authorize(hass, connection, msg) -> bool:
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
    vol.Required("type"): "omote_manager/pairing/candidate/status",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_candidate_status(
    hass: HomeAssistant, connection, msg: dict
) -> None:
    if not _authorize(hass, connection, msg):
        return
    identities = hass.data.get(IDENTITY_STORE_KEY)
    if identities is None:
        connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
                              "Candidate identity store unavailable")
        return
    try:
        result = identities.status(msg["entry_id"])
    except CandidateIdentityError:
        connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
                              "Candidate identity storage invalid or unavailable")
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): "omote_manager/pairing/candidate/prepare",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_candidate_prepare(
    hass: HomeAssistant, connection, msg: dict
) -> None:
    """Explicit administrator action, local HA storage only."""
    if not _authorize(hass, connection, msg):
        return
    identities = hass.data.get(IDENTITY_STORE_KEY)
    if identities is None:
        connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
                              "Candidate identity store unavailable")
        return
    try:
        result = await identities.async_prepare(msg["entry_id"])
    except CandidateIdentityError:
        connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
                              "Candidate key cannot be safely prepared")
        return
    # No DER private key, PIN, nonce, signature or access token is returned.
    connection.send_result(msg["id"], result)


def register_candidate_identity_websockets(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_candidate_status)
    websocket_api.async_register_command(hass, ws_candidate_prepare)
