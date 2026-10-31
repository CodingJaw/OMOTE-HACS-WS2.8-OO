"""Read-only OMOTE configuration and network sensors."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create sensors for a remote."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        OmoteFileCountSensor(coordinator, entry),
        OmoteApiVersionSensor(coordinator, entry),
    ])


class OmoteBaseSensor(CoordinatorEntity, SensorEntity):
    """Shared device identity and coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="OMOTE Community",
            model="OMOTE object-oriented firmware",
            configuration_url=f"http://{entry.data['host']}:{entry.data.get('port', 80)}/api/status",
        )


class OmoteFileCountSensor(OmoteBaseSensor):
    """Count available JSON configuration files."""

    _attr_name = "Configuration files"
    _attr_icon = "mdi:file-code-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_files"

    @property
    def native_value(self):
        return len(self.coordinator.data["files"])


class OmoteApiVersionSensor(OmoteBaseSensor):
    """Report the firmware's configuration API protocol version."""

    _attr_name = "Configuration API"
    _attr_icon = "mdi:api"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_api"

    @property
    def native_value(self):
        return self.coordinator.data["status"]["api"]
