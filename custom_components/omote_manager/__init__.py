"""OMOTE Manager Home Assistant integration.

The current OMOTE firmware does not offer transactional configuration writes.
This version supports read-only monitoring, local backups, and HA-only drafts.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import OmoteApi, OmoteApiError
from .const import DOMAIN
from .coordinator import OmoteCoordinator
from .panel import async_register_manager_panel
from .safe_files import is_exportable_json
from .workspace_store import WorkspaceStore
from .workspace_ws import STORE_KEY

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]
SERVICE_BACKUP = "backup_configuration"
SERVICE_REFRESH = "refresh"
ENTRY_SCHEMA = vol.Schema({vol.Required("entry_id"): str})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration and read-only management actions."""
    hass.data.setdefault(DOMAIN, {})
    workspace = WorkspaceStore(hass)
    await workspace.async_load()
    hass.data[STORE_KEY] = workspace
    await async_register_manager_panel(hass)

    def _coordinator(call: ServiceCall) -> OmoteCoordinator:
        entry_id = call.data["entry_id"]
        coordinator = hass.data[DOMAIN].get(entry_id)
        if coordinator is None:
            raise HomeAssistantError("OMOTE entry not found or not loaded")
        return coordinator

    async def async_refresh(call: ServiceCall) -> None:
        """Immediately refresh status and filesystem inventory."""
        await _coordinator(call).async_request_refresh()

    async def async_backup(call: ServiceCall) -> None:
        """Store the last three nonsensitive snapshots under HA .storage.

        Files are backed up as their original UTF-8 text, preserving comments.
        This is not a full-device backup; secrets and device settings are excluded.
        """
        coordinator = _coordinator(call)
        entry_id = call.data["entry_id"]
        api = coordinator.api
        try:
            await api.status()
            available = await api.files()
            saved = {}
            total = 0
            for path in available:
                if not is_exportable_json(path):
                    continue
                content = await api.read_file(path, verify_json=True)
                total += len(content.encode("utf-8"))
                if total > 512 * 1024:
                    raise HomeAssistantError("Backup exceeds 512 KiB safety limit")
                saved[path] = content
            if not saved:
                raise HomeAssistantError("No eligible configuration files found")
            digest = hashlib.sha256()
            for path, content in sorted(saved.items()):
                digest.update(path.encode("utf-8"))
                digest.update(b"\x00")
                digest.update(content.encode("utf-8"))
                digest.update(b"\x00")
            snapshot = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "files": saved,
                "sha256": digest.hexdigest(),
            }
            store = Store(hass, 1, f"{DOMAIN}.backups_{entry_id}")
            prior = await store.async_load() or {}
            history = prior.get("snapshots", [])
            history.append(snapshot)
            await store.async_save({"snapshots": history[-3:]})
            _LOGGER.info(
                "Saved OMOTE backup for %s: %d files, SHA256 %s",
                entry_id, len(saved), digest.hexdigest(),
            )
        except OmoteApiError as exc:
            raise HomeAssistantError(f"OMOTE backup failed: {exc}") from exc

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, async_refresh, schema=ENTRY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_BACKUP, async_backup, schema=ENTRY_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Connect to one independently configured OMOTE remote."""
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
    """Stop polling and unload entities for a remote."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
