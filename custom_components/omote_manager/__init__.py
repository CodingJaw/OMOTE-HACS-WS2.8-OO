"""OMOTE Manager integration.

Read-only firmware access by default. Explicit deployment will require a
verified, transactional firmware API in a future milestone.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OmoteApi
from .const import DOMAIN
from .coordinator import OmoteCoordinator

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Connect to an individual OMOTE remote."""
    api = OmoteApi(
        async_get_clientsession(hass),
        entry.data["host"],
        entry.data.get("port", 80),
    )
    coordinator = OmoteCoordinator(hass, api, entry.data["host"])
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload all entities and stop polling."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
