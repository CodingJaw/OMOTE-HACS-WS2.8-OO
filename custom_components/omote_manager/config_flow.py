"""OMOTE config flow for HA Core 2024.9.1.

Supports manual IP/host setup and *confirmed* zeroconf discovery.
mDNS TXT is an untrusted hint, never authentication or deployment approval.
"""
from __future__ import annotations

import ipaddress
import re

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OmoteApi, OmoteApiError
from .const import DOMAIN
from .form import normalize_host, user_form_schema

_DISCOVERY_ID = re.compile(r"^[a-f0-9]{12}$")


class OmoteManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one OMOTE device, never enabling firmware mutations."""

    VERSION = 1

    def _matching_entry(self, host: str, port: int, hostname: str = "",
                        discovery_id: str = "") -> bool:
        """Do not rediscover an already manually configured endpoint."""
        aliases = {host}
        if hostname:
            aliases.add(hostname.casefold().removesuffix(".local") + ".local")
        for entry in self._async_current_entries():
            data = entry.data
            if discovery_id and data.get("discovery_id") == discovery_id:
                return True
            if data.get("port", 80) == port and data.get("host", "").casefold() in aliases:
                return True
        return False

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
                    if self._matching_entry(host, port):
                        return self.async_abort(reason="already_configured")
                    await self.async_set_unique_id(f"{host}:{port}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=status.get("hostname") or host,
                        data={"host": host, "port": port},
                    )
        return self.async_show_form(
            step_id="user", data_schema=user_form_schema(), errors=errors
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo):
        """Offer an explicitly confirmed discovery; never automatically pair."""
        properties = discovery_info.properties
        if not isinstance(properties, dict):
            return self.async_abort(reason="invalid_discovery")
        device_id = properties.get("id")
        api = properties.get("api")
        model = properties.get("model")
        if (not isinstance(device_id, str)
                or not _DISCOVERY_ID.fullmatch(device_id.casefold())
                or api != "omote-config-v1"
                or model != "waveshare28v2"):
            return self.async_abort(reason="invalid_discovery")
        try:
            address = ipaddress.ip_address(discovery_info.host)
        except ValueError:
            return self.async_abort(reason="invalid_discovery")
        # Current v1 transport handles IPv4 only, not bracketed IPv6 URLs.
        if (not isinstance(address, ipaddress.IPv4Address) or not address.is_private
                or address.is_loopback or address.is_link_local or address.is_multicast):
            return self.async_abort(reason="invalid_discovery")
        host = str(address)
        port = discovery_info.port
        if type(port) is not int or not (1 <= port <= 65535):
            return self.async_abort(reason="invalid_discovery")
        try:
            status = await OmoteApi(
                async_get_clientsession(self.hass), host, port
            ).status()
        except OmoteApiError:
            return self.async_abort(reason="cannot_connect")
        reported_name = status.get("hostname", "")
        if not isinstance(reported_name, str):
            reported_name = ""
        device_id = device_id.casefold()
        if self._matching_entry(host, port, reported_name, device_id):
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(f"omote:{device_id}")
        self._abort_if_unique_id_configured()
        # Discovery is an unauthenticated network announcement. IP address
        # changes for existing devices must not silently replace a trusted host.
        self._discovery = {
            "host": host,
            "port": port,
            "discovery_id": device_id,
            "title": reported_name or "OMOTE",
        }
        self.context["title_placeholders"] = {
            "name": reported_name or "OMOTE",
            "host": host,
        }
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input=None):
        """Require an administrator to confirm the discovered host."""
        if not hasattr(self, "_discovery"):
            return self.async_abort(reason="invalid_discovery")
        if user_input is not None:
            entry = self._discovery
            if self._matching_entry(
                entry["host"], entry["port"], discovery_id=entry["discovery_id"]
            ):
                return self.async_abort(reason="already_configured")
            return self.async_create_entry(
                title=entry["title"],
                data={
                    "host": entry["host"],
                    "port": entry["port"],
                    "discovery_id": entry["discovery_id"],
                },
            )
        return self.async_show_form(
            step_id="zeroconf_confirm", data_schema=vol.Schema({})
        )
