"""Config flow compatible with Home Assistant Core 2024.9.1."""
from __future__ import annotations

import ipaddress
import logging

from aiohttp import ClientError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OmoteApi, OmoteApiError
from .const import DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _valid_host(value: str) -> str:
    """Accept a hostname or literal IPv4 address (no URI or path)."""
    host = value.strip().lower()
    if not host or len(host) > 253 or any(c in host for c in "/:@?#% \\"):
        raise vol.Invalid("Enter a hostname or IPv4 address, not a URL")
    try:
        ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        if not all(
            part and len(part) <= 63 and
            part[0].isalnum() and part[-1].isalnum() and
            all(c.isalnum() or c == "-" for c in part)
            for part in host.split(".")
        ):
            raise vol.Invalid("Invalid hostname")
    return host


class OmoteManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure an OMOTE instance using its local IP or hostname."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input["host"]
            port = user_input["port"]
            try:
                client = OmoteApi(async_get_clientsession(self.hass), host, port)
                status = await client.status()
            except (OmoteApiError, ClientError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=status.get("hostname") or host,
                    data={"host": host, "port": port},
                )
        schema = vol.Schema(
            {
                vol.Required("host"): _valid_host,
                vol.Required("port", default=DEFAULT_PORT):
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
