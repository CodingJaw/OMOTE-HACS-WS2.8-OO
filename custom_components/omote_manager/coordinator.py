"""Polling coordinator for an OMOTE remote."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import OmoteApi, OmoteApiError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class OmoteCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the status and configuration inventory of one OMOTE remote."""

    def __init__(self, hass: HomeAssistant, api: OmoteApi, host: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{host}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self.api.status()
            files = await self.api.files()
            return {"status": status, "files": files}
        except OmoteApiError as exc:
            raise UpdateFailed(str(exc)) from exc
