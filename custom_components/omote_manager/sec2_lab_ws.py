"""Admin-only, default-OFF Security2 LAB test for a registered OMOTE.

This endpoint does NOT pair, persist trust, update NVS, deploy configs or OTA.
It is available only when OMOTE_SEC2_LAB_ENABLE=1 is set in HA's own
environment. Espressif Security2 is bundled under the OMOTE namespace;
no IDF_PATH or runtime download is used. No browser target IP is accepted.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .candidate_identity_ws import IDENTITY_STORE_KEY
from .const import DOMAIN
from .sec2_lab_espidf import LabPrerequisiteError, load_official_security2
from .sec2_lab_http import LabHttpTransport
from .sec2_lab_session import LabSessionError, run_lab_session

_LAB_LOCKS_KEY = f"{DOMAIN}_security2_lab_locks"
_PIN = re.compile(r"[0-9]{6}\Z", re.ASCII)


def _enabled() -> bool:
    return os.environ.get("OMOTE_SEC2_LAB_ENABLE", "") == "1"


def _admin_and_entry(hass: HomeAssistant, connection, msg: dict):
    if connection.user is None or not connection.user.is_admin:
        connection.send_error(
            msg["id"], websocket_api.ERR_UNAUTHORIZED, "Administrator required"
        )
        return None
    entry_id = msg.get("entry_id")
    entry = next(
        (candidate for candidate in hass.config_entries.async_entries(DOMAIN)
         if candidate.entry_id == entry_id), None
    )
    if entry is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND,
                              "Unknown OMOTE remote")
    return entry


def _local_host(entry) -> str:
    """Never allow a browser-specified endpoint or a nonlocal URL."""
    host = entry.data.get("host")
    if type(host) is not str:
        raise ValueError("Invalid registered host")
    ip = ipaddress.IPv4Address(host)
    if (not ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_unspecified or ip.is_reserved):
        raise ValueError("LAB only supports registered local IPv4 hosts")
    return str(ip)


@websocket_api.websocket_command({
    vol.Required("type"): "omote_manager/pairing/lab/readiness",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_lab_readiness(hass: HomeAssistant, connection, msg: dict):
    entry = _admin_and_entry(hass, connection, msg)
    if entry is None:
        return
    try:
        _local_host(entry)
        valid_host = True
    except ValueError:
        valid_host = False
    bundled_ready = False
    diagnostic = "lab_not_enabled"
    if _enabled():
        try:
            load_official_security2()  # Local dependency inspection only.
            bundled_ready = True
            diagnostic = "bundled_security2_ready"
        except LabPrerequisiteError as exc:
            diagnostic = str(exc)
        except Exception:
            diagnostic = "bundled_security2_unavailable"
    connection.send_result(msg["id"], {
        "lab_only": True,
        "enabled": _enabled(),
        "security2_client": "bundled-esp-idf-v5.4.2",
        "bundled_client_ready": bundled_ready,
        "client_diagnostic": diagnostic,
        "registered_lan_ipv4": valid_host,
        "can_attempt": _enabled() and valid_host and bundled_ready,
        "paired": False,
        "trusted": False,
        "deployment_enabled": False,
        "ota_enabled": False,
    })


@websocket_api.websocket_command({
    vol.Required("type"): "omote_manager/pairing/lab/test",
    vol.Required("entry_id"): str,
    vol.Required("pin"): str,
    vol.Required("ack_lab_only"): bool,
})
@websocket_api.async_response
async def ws_lab_test(hass: HomeAssistant, connection, msg: dict):
    entry = _admin_and_entry(hass, connection, msg)
    if entry is None:
        return
    if not _enabled() or msg["ack_lab_only"] is not True:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_ALLOWED,
                              "Explicit LAB mode and approval required")
        return
    # No private key, PIN, arbitrary URL or cryptographic signature is ever
    # returned by this WebSocket. Keep untrusted device key informational.
    if not _PIN.fullmatch(msg["pin"]):
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT,
                              "Six-digit touchscreen PIN required")
        return
    try:
        host = _local_host(entry)
    except ValueError:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_ALLOWED,
                              "Only a registered private LAN IPv4 remote can be tested")
        return
    identities = hass.data.get(IDENTITY_STORE_KEY)
    if identities is None:
        connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
                              "Local HA candidate key store unavailable")
        return
    try:
        if not identities.status(entry.entry_id)["prepared"]:
            connection.send_error(msg["id"], websocket_api.ERR_NOT_ALLOWED,
                                  "Prepare HA candidate identity first")
            return
    except Exception:
        connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
                              "HA candidate identity invalid")
        return
    locks = hass.data.setdefault(_LAB_LOCKS_KEY, {})
    lock = locks.setdefault(entry.entry_id, asyncio.Lock())
    if lock.locked():
        connection.send_error(msg["id"], websocket_api.ERR_NOT_ALLOWED,
                              "A laboratory attempt is already in progress")
        return
    async with lock:
        try:
            # Import the official source only after admin, entry and PIN
            # preflight. No listener is opened on HA and no keys are created.
            official_security2 = load_official_security2()
            result = await run_lab_session(
                host=host, pin=msg["pin"], entry_id=entry.entry_id,
                identities=identities, security_factory=official_security2,
                transport_factory=LabHttpTransport, ack_lab_only=True,
            )
        except LabPrerequisiteError as exc:
            connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
                                  "Security2 LAB prerequisites: " + str(exc))
            return
        except LabSessionError as exc:
            connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
                                  "Security2 LAB stage failed: " + exc.stage)
            return
        except Exception:
            connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR,
                                  "Security2 LAB test unavailable")
            return
    # Public fingerprints only. Not a trusted pairing, no capability change.
    connection.send_result(msg["id"], result)


def register_lab_websockets(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_lab_readiness)
    websocket_api.async_register_command(hass, ws_lab_test)
