"""Binary sensor: has the Garmin watch stopped syncing?"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DEFAULT_SYNC_STALE_HOURS, OPT_SYNC_STALE_HOURS
from .coordinator import GarminConfigEntry, GarminCoordinator
from .entity import device_info
from .values import dig, parse_timestamp

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: GarminConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the binary sensors."""
    async_add_entities([GarminSyncStaleSensor(entry.runtime_data.coordinators["daily"], entry)])


class GarminSyncStaleSensor(CoordinatorEntity[GarminCoordinator], BinarySensorEntity):
    """On when the last watch sync is older than the configured number of hours."""

    _attr_has_entity_name = True
    _attr_translation_key = "sync_stale"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GarminCoordinator, entry: GarminConfigEntry) -> None:
        """Set up the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sync_stale"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool | None:
        """Whether the last sync is too old (unknown without a sync timestamp)."""
        if not self.coordinator.data:
            return None
        last = parse_timestamp(dig(self.coordinator.data, "summary", "lastSyncTimestampGMT"))
        if last is None:
            return None
        hours = self._entry.options.get(OPT_SYNC_STALE_HOURS, DEFAULT_SYNC_STALE_HOURS)
        return dt_util.utcnow() - last > timedelta(hours=hours)
