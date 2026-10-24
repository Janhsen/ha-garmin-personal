"""Calendar entity: the latest activities from Garmin Connect as calendar events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import GarminConfigEntry, GarminCoordinator
from .entity import device_info
from .values import dig, parse_timestamp, to_number

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: GarminConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the calendar entity."""
    async_add_entities([GarminActivityCalendar(entry.runtime_data.coordinators["activities"], entry)])


def _length(distance_m: float, hass: HomeAssistant | None) -> str:
    """A distance in the unit system of Home Assistant (km or mi); kilometres without Home Assistant."""
    units = getattr(getattr(hass, "config", None), "units", None)
    if units is not None and hasattr(units, "length") and hasattr(units, "length_unit"):
        try:
            return f"{units.length(distance_m, 'm'):.2f} {units.length_unit}"
        except (TypeError, ValueError):
            pass
    return f"{distance_m / 1000:.2f} km"


def activity_end(start: datetime, activity: Mapping[str, Any]) -> datetime | None:
    """End of an activity: the elapsed time (pauses included) if Garmin states it, else the timer duration."""
    duration = to_number(activity.get("duration"))
    if duration is None or duration <= 0:
        return None
    elapsed = to_number(activity.get("elapsedDuration"))
    # Elapsed time can never be shorter than the timer time; anything else is not used.
    if elapsed is not None and elapsed >= duration:
        duration = elapsed
    return start + timedelta(seconds=duration)


def activity_event(activity: Mapping[str, Any], hass: HomeAssistant | None = None) -> CalendarEvent | None:
    """One activity as a calendar event, from Garmin's start time and duration only."""
    start = parse_timestamp(activity.get("startTimeGMT"))
    end = activity_end(start, activity) if start is not None else None
    if start is None or end is None:
        return None
    parts = []
    distance = to_number(activity.get("distance"))
    if distance:
        parts.append(_length(distance, hass))
    calories = to_number(activity.get("calories"))
    if calories:
        parts.append(f"{round(calories)} kcal")
    heart_rate = to_number(activity.get("averageHR"))
    if heart_rate:
        parts.append(f"{round(heart_rate)} bpm")
    name = activity.get("activityName") or dig(activity, "activityType", "typeKey") or "Garmin"
    return CalendarEvent(
        start=start,
        end=end,
        summary=str(name),
        description=", ".join(parts) or None,
        uid=str(activity.get("activityId")) if activity.get("activityId") is not None else None,
    )


class GarminActivityCalendar(CoordinatorEntity[GarminCoordinator], CalendarEntity):
    """The latest activities (as many as the integration fetches, about 20).

    Descriptions use the unit system of Home Assistant for the distance; calories and heart rate are
    kcal and bpm. The end of an event is the elapsed time when Garmin delivers ``elapsedDuration``.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "activities"

    def __init__(self, coordinator: GarminCoordinator, entry: GarminConfigEntry) -> None:
        """Set up the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_activities_calendar"
        self._attr_device_info = device_info(entry)

    def _events(self) -> list[CalendarEvent]:
        data = self.coordinator.data or {}
        hass = getattr(self, "hass", None)
        events = [activity_event(a, hass) for a in data.get("activities") or [] if isinstance(a, Mapping)]
        return sorted((e for e in events if e is not None), key=lambda e: e.start)

    @property
    def event(self) -> CalendarEvent | None:
        """The running activity, otherwise the next upcoming one; never a finished one."""
        now = dt_util.utcnow()
        events = self._events()
        for event in events:
            if event.start <= now < event.end:
                return event
        upcoming = [e for e in events if e.start > now]
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Activities that overlap the requested range."""
        return [e for e in self._events() if e.end > start_date and e.start < end_date]
