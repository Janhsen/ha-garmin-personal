"""Data update coordinators.

One coordinator per data group, each with its own interval, so a slow or broken
endpoint never holds back the others. Inside a group, endpoints are fetched one
after another and a failing endpoint only leaves its own values empty.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import GarminAuthError, GarminError, GarminPersonalApi, GarminRateLimitError
from .const import DOMAIN
from .repairs import update_key_expiry_issue

_LOGGER = logging.getLogger(__name__)

Calls = dict[str, Callable[[], Awaitable[Any]]]
CallBuilder = Callable[[GarminPersonalApi, date], Calls]


@dataclass
class GarminRuntimeData:
    """What a config entry keeps at runtime."""

    api: GarminPersonalApi
    coordinators: dict[str, GarminCoordinator] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


type GarminConfigEntry = ConfigEntry[GarminRuntimeData]


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, Mapping):
        return all(item is None for item in value.values())
    if isinstance(value, list):
        return not value
    return False


def unwrap_sleep(sleep: Any) -> Any:
    """Flatten ``dailySleepDTO`` if Garmin nests the sleep values."""
    if isinstance(sleep, Mapping) and isinstance(sleep.get("dailySleepDTO"), Mapping):
        return {**sleep, **sleep["dailySleepDTO"]}
    return sleep


class GarminCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches one group of endpoints on a fixed interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GarminConfigEntry,
        api: GarminPersonalApi,
        group: str,
        interval: timedelta,
        build_calls: CallBuilder,
        *,
        sticky: tuple[str, ...] = (),
    ) -> None:
        """Set up the coordinator.

        ``sticky`` lists keys whose last good value is kept when Garmin returns
        nothing (for example last night's sleep during the early morning hours).
        """
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {group} ({entry.title})",
            update_interval=interval,
        )
        self.api = api
        self.group = group
        self._build_calls = build_calls
        self._sticky = sticky
        self._warned: set[str] = set()

    async def _async_update_data(self) -> dict[str, Any]:
        today = dt_util.now().date()
        calls = self._build_calls(self.api, today)
        results: dict[str, Any] = {}
        failures: list[str] = []
        for key, call in calls.items():
            try:
                results[key] = await call()
            except GarminAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except GarminRateLimitError as err:
                # Stop the whole cycle: hammering the remaining endpoints makes it worse.
                raise UpdateFailed(f"{self.group}: {err}") from err
            except GarminError as err:
                _LOGGER.debug("%s: %s failed: %s", self.group, key, err)
                if key not in self._warned:  # once per endpoint, not every cycle
                    self._warned.add(key)
                    _LOGGER.warning("%s: endpoint %s failed: %s", self.group, key, err)
                failures.append(f"{key}: {err}")
                results[key] = None
            else:
                self._warned.discard(key)
        if calls and len(failures) == len(calls):
            raise UpdateFailed("; ".join(failures))
        if "sleep" in results:
            results["sleep"] = unwrap_sleep(results["sleep"])
        previous = self.data or {}
        for key in self._sticky:
            if _is_empty(results.get(key)) and not _is_empty(previous.get(key)):
                results[key] = previous[key]
        results["_day"] = today.isoformat()
        return results


class GarminActivityCoordinator(GarminCoordinator):
    """Like the others, and additionally reports activities it has not seen before."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Set up the coordinator and its small store of the last seen activity id."""
        super().__init__(*args, **kwargs)
        entry: GarminConfigEntry = args[1]
        self._store: Store[dict[str, int]] = Store(
            self.hass, 1, f"{DOMAIN}.{entry.entry_id}.activities"
        )
        self._last_id: int | None = None
        self._loaded = False

    async def _async_update_data(self) -> dict[str, Any]:
        if not self._loaded:
            stored = await self._store.async_load()
            self._last_id = (stored or {}).get("last_id")
            self._loaded = True
        data = await super()._async_update_data()
        activities = [a for a in (data.get("activities") or []) if isinstance(a, Mapping)]
        ids = [a["activityId"] for a in activities if isinstance(a.get("activityId"), int)]
        newest = max(ids, default=None)
        new: list[Mapping[str, Any]] = []
        if newest is not None:
            # On the very first run nothing is "new": that would flood automations.
            if self._last_id is not None:
                new = [
                    a
                    for a in activities
                    if isinstance(a.get("activityId"), int) and a["activityId"] > self._last_id
                ]
                new.sort(key=lambda a: a["activityId"])
            if self._last_id is None or newest > self._last_id:
                self._last_id = newest
                await self._store.async_save({"last_id": newest})
        data["new_activities"] = new
        return data


class GarminProfileCoordinator(GarminCoordinator):
    """Slow-changing data; also refreshes the key-expiry repair issue."""

    async def _async_update_data(self) -> dict[str, Any]:
        entry = self.config_entry
        if entry is not None:
            update_key_expiry_issue(self.hass, entry)
        return await super()._async_update_data()


# ---------------------------------------------------------------------------
# Which endpoints each group fetches
# ---------------------------------------------------------------------------


def make_daily_calls(intraday: bool) -> CallBuilder:
    """Today's activity-tracker values.

    The heart rate and body battery series are only needed for the optional
    intraday attributes, so they are only requested when that option is on.
    """

    def daily_calls(api: GarminPersonalApi, today: date) -> Calls:
        calls: Calls = {
            "summary": lambda: api.get_daily_summary(today),
            "spo2": lambda: api.get_spo2(today),
            "hydration": lambda: api.get_hydration(today, today),
        }
        if intraday:
            calls["heart_rate"] = lambda: api.get_heart_rate(today)
            calls["body_battery"] = lambda: api.get_body_battery(today, today)
        return calls

    return daily_calls


def sleep_calls(api: GarminPersonalApi, today: date) -> Calls:
    """Last night's sleep and HRV."""
    return {
        "sleep": lambda: api.get_daily_sleep(today),
        "hrv_summaries": lambda: api.get_hrv_summaries(today - timedelta(days=7), today),
    }


def body_calls(api: GarminPersonalApi, today: date) -> Calls:
    """Weight, body composition and fitness age."""
    return {
        "weight": lambda: api.get_weight_range(today - timedelta(days=90), today),
        "fitness_age": lambda: api.get_fitness_age(today),
    }


def activity_calls(api: GarminPersonalApi, today: date) -> Calls:
    """Latest activities and today's wellness activities."""
    return {
        "activities": lambda: api.search_activities(limit=20),
        "wellness_activities": lambda: api.get_wellness_activities(today, today),
    }


def profile_calls(api: GarminPersonalApi, today: date) -> Calls:
    """Account settings and heart rate zones."""
    return {
        "profile": lambda: api.get_profile_settings(),
        "hr_zones": lambda: api.get_hr_zones(),
    }
