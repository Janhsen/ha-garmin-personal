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

    async def async_added_to_hass(self) -> None:
        """Report activities the coordinator found before this entity existed.

        The first refresh runs before the platform is set up, and a coordinator entity does
        not see data that was already there when it is added.
        """
        await super().async_added_to_hass()
        self._report_new()

    def _report_new(self) -> bool:
        """Fire an event for every activity not reported yet; returns whether one fired."""
        fired = False
        # new_activities stays in the data until the next refresh, so remember what was
        # already reported (listener calls also happen after failed updates).
        for activity in (self.coordinator.data or {}).get("new_activities") or []:
            activity_id = activity.get("activityId")
            if isinstance(activity_id, int) and (
                self._last_reported is None or activity_id > self._last_reported
            ):
                self._last_reported = activity_id
                self._trigger_event(EVENT_ACTIVITY_FINISHED, _event_data(activity))
                # One state write per event, or a second activity in the same update
                # would overwrite the first before it is recorded.
                self.async_write_ha_state()
                fired = True
        return fired

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self._report_new():
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
