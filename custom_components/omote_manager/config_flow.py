"""OMOTE Manager config flow compatible with Home Assistant Core 2024.9.1."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OmoteApi, OmoteApiError
from .const import DOMAIN
from .form import normalize_host, user_form_schema


class OmoteManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure an OMOTE endpoint using its LAN host and port."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                host = normalize_host(user_input["host"])
            except vol.Invalid:
                errors["host"] = "invalid_host"
            else:
                port = user_input["port"]
                try:
                    client = OmoteApi(async_get_clientsession(self.hass), host, port)
                    status = await client.status()
                except OmoteApiError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(f"{host}:{port}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=status.get("hostname") or host,
                        data={"host": host, "port": port},
                    )
        return self.async_show_form(
            step_id="user", data_schema=user_form_schema(), errors=errors
        )
