"""Event entity: fires when a new activity shows up in Garmin Connect."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import EVENT_ACTIVITY_FINISHED
from .coordinator import GarminConfigEntry, GarminCoordinator
from .entity import device_info
from .values import dig

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: GarminConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the event entity."""
    async_add_entities([GarminActivityEvent(entry.runtime_data.coordinators["activities"], entry)])


class GarminActivityEvent(CoordinatorEntity[GarminCoordinator], EventEntity):
    """One event per newly seen activity (not on the very first refresh)."""

    _attr_has_entity_name = True
    _attr_translation_key = "activity"
    _attr_event_types = [EVENT_ACTIVITY_FINISHED]

    def __init__(self, coordinator: GarminCoordinator, entry: GarminConfigEntry) -> None:
        """Set up the entity."""
        super().__init__(coordinator)
        self._last_reported: int | None = None
        self._attr_unique_id = f"{entry.entry_id}_activity"
        self._attr_device_info = device_info(entry)

    @callback
    def _handle_coordinator_update(self) -> None:
        # new_activities stays in the data until the next refresh, so remember
        # what was already reported (listener calls also happen after failed updates).
        for activity in (self.coordinator.data or {}).get("new_activities", []):
            activity_id = activity.get("activityId")
            if isinstance(activity_id, int) and (
                self._last_reported is None or activity_id > self._last_reported
            ):
                self._last_reported = activity_id
                self._trigger_event(EVENT_ACTIVITY_FINISHED, _event_data(activity))
        super()._handle_coordinator_update()


def _event_data(activity: Any) -> dict[str, Any]:
    return {
        "activity_id": activity.get("activityId"),
        "name": activity.get("activityName"),
        "type": dig(activity, "activityType", "typeKey"),
        "start_time_gmt": activity.get("startTimeGMT"),
        "distance": activity.get("distance"),
        "duration": activity.get("duration"),
        "calories": activity.get("calories"),
    }
