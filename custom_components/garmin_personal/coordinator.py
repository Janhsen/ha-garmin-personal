"""Data update coordinators.

One coordinator per data group, each with its own interval, so a slow or broken
endpoint never holds back the others. Inside a group, endpoints are fetched one
after another and a failing endpoint only leaves its own values empty.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import GarminAuthError, GarminError, GarminPersonalApi, GarminRateLimitError
from .const import DAILY_FULL_REFRESH, DOMAIN
from .history import append_points, manager_for
from .intraday import (
    HISTORY_SERIES,
    SERIES,
    closed_hours,
    drop_straddling,
    fetch_series,
    hourly_aggregate,
    merge_points,
    note_unknown_format,
)
from .repairs import update_key_expiry_issue
from .stats_writer import write_hourly
from .values import dig, parse_timestamp

_LOGGER = logging.getLogger(__name__)

Calls = dict[str, Callable[[], Awaitable[Any]]]
CallBuilder = Callable[[GarminPersonalApi, date], Calls]


@dataclass
class GarminRuntimeData:
    """What a config entry keeps at runtime."""

    api: GarminPersonalApi
    coordinators: dict[str, GarminCoordinator] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    history: Any = None  # HistoryManager, created on first use (history.manager_for)


type GarminConfigEntry = ConfigEntry[GarminRuntimeData]


# Without a successful cycle for this long (but at least GRACE_MIN), the entities of a
# group turn unavailable instead of silently showing old data.
GRACE_MIN = timedelta(minutes=15)
GRACE_CYCLES = 3

# Yesterday's hours are fetched again on the first full refresh of a day and, until this local
# hour, after every new watch sync (late evening data often arrives with the first morning sync).
YESTERDAY_RETRY_UNTIL_HOUR = 10


def _is_empty(value: Any) -> bool:
    """No usable content, looking through nested answers (``dailySleepDTO`` and the like)."""
    if value is None:
        return True
    if isinstance(value, Mapping):
        return all(_is_empty(item) for item in value.values())
    if isinstance(value, list):
        return all(_is_empty(item) for item in value)
    return False


def _has_no_measurement(key: str, value: Any) -> bool:
    """``_is_empty`` plus: a sleep answer without a positive duration is no measurement."""
    if _is_empty(value):
        return True
    if key == "sleep" and isinstance(value, Mapping) and "sleepTimeSeconds" in value:
        seconds = value["sleepTimeSeconds"]
        return not (isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0)
    return False


def _update_failed(message: str, retry_after: float | None = None) -> UpdateFailed:
    """``UpdateFailed`` carrying Garmin's Retry-After (the argument exists since HA 2025.x)."""
    if retry_after is None:
        return UpdateFailed(message)
    try:
        return UpdateFailed(message, retry_after=retry_after)
    except TypeError:  # older Home Assistant: keep the value for whoever wants it
        err = UpdateFailed(message)
        err.retry_after = retry_after  # type: ignore[attr-defined]
        return err


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
        self._cycle_day: date = dt_util.now().date()

    # Keys whose value belongs to one calendar day and must never be carried into the
    # next one (``None``: all keys of the group).
    DAY_BOUND: frozenset[str] | None = frozenset({"wellness_activities"})
    _last_ok: datetime | None = None

    def _is_day_bound(self, key: str) -> bool:
        return self.DAY_BOUND is None or key in self.DAY_BOUND

    def _carry(self, key: str, previous: Mapping[str, Any], today: date) -> Any:
        """The last value of ``key`` for a skipped or failed endpoint (never from another day)."""
        value = previous.get(key)
        if value is not None and self._is_day_bound(key) and previous.get("_day") != today.isoformat():
            return None
        return value

    def _hold_or_fail(
        self,
        message: str,
        previous: Mapping[str, Any],
        today: date,
        retry_after: float | None = None,
    ) -> dict[str, Any]:
        """Keep the last data through a short outage, otherwise report the failure.

        One missed cycle must not turn dozens of entities unavailable, but data that is
        too old (or from yesterday, for the day-bound daily group) must not look current.
        """
        grace = max(GRACE_MIN, (self.update_interval or timedelta()) * GRACE_CYCLES)
        fresh = self._last_ok is not None and dt_util.utcnow() - self._last_ok < grace
        same_day = self.DAY_BOUND is not None or previous.get("_day") == today.isoformat()
        if previous and fresh and same_day:
            _LOGGER.warning("%s: update failed, keeping the last data: %s", self.group, message)
            return dict(previous)
        raise _update_failed(message, retry_after)

    async def _skip(self, key: str, results: dict[str, Any]) -> bool:
        """Hook: skip one endpoint this cycle (its last value is carried over)."""
        return False

    async def _after_update(self, results: dict[str, Any], skipped: bool) -> None:
        """Hook: called with the finished results."""

    async def _async_update_data(self) -> dict[str, Any]:
        today = dt_util.now().date()
        self._cycle_day = today
        calls = self._build_calls(self.api, today)
        previous = self.data or {}
        results: dict[str, Any] = {}
        failures: list[str] = []
        executed = 0
        skipped = False
        for key, call in calls.items():
            if await self._skip(key, results):
                skipped = True
                results[key] = self._carry(key, previous, today)
                continue
            executed += 1
            try:
                results[key] = await call()
            except GarminAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except GarminRateLimitError as err:
                # Stop the whole cycle: hammering the remaining endpoints makes it worse.
                return self._hold_or_fail(
                    f"{self.group}: {err}", previous, today, err.retry_after
                )
            except (GarminError, AttributeError, TypeError, KeyError, ValueError) as err:
                # Includes answers of an unexpected shape: one broken endpoint must not
                # take the group down with it.
                _LOGGER.debug("%s: %s failed: %s", self.group, key, err)
                if key not in self._warned:  # once per endpoint, not every cycle
                    self._warned.add(key)
                    _LOGGER.warning("%s: endpoint %s failed: %s", self.group, key, err)
                failures.append(f"{key}: {err}")
                results[key] = self._carry(key, previous, today)
            else:
                self._warned.discard(key)
        if executed and len(failures) == executed:
            return self._hold_or_fail("; ".join(failures), previous, today)
        if "sleep" in results:
            results["sleep"] = unwrap_sleep(results["sleep"])
        for key in self._sticky:
            if _has_no_measurement(key, results.get(key)) and not _is_empty(previous.get(key)):
                results[key] = previous[key]
        results["_day"] = today.isoformat()
        await self._after_update(results, skipped)
        self._last_ok = dt_util.utcnow()
        return results


class GarminDailyCoordinator(GarminCoordinator):
    """Polls the daily summary often and the rest only after a new watch sync.

    The summary carries ``lastSyncTimestampGMT``. When it changes, the remaining
    daily endpoints are fetched and the follower groups (sleep, body, activities)
    are asked to refresh. Without a change the rest is refreshed at most hourly.
    """

    # Everything here is "today": nothing may be carried over into the next day.
    DAY_BOUND = None
    _primed = False  # False until the first successful cycle after the start

    # Hourly long-term statistics from the day's heart rate, Body Battery and SpO2 series.
    _hourly_stats = False
    _history_auto = False
    _intraday_day: date | None = None  # the day for which the last write was started
    _yesterday_done: date | None = None  # the day on which yesterday's hours were last written
    _intraday_lock: asyncio.Lock | None = None
    _jobs: set[Any]

    def __init__(
        self, *args: Any, hourly_stats: bool = False, history_auto: bool = False, **kwargs: Any
    ) -> None:
        """Set up the coordinator; ``followers`` are filled in after creation."""
        super().__init__(*args, **kwargs)
        self.followers: list[GarminCoordinator] = []
        self._last_sync: Any = None
        self._last_full: Any = None
        self._hourly_stats = hourly_stats
        self._history_auto = history_auto
        self._jobs = set()

    def _start_job(self, coro: Any) -> None:
        """Run a side job in the background, bound to the config entry so that unloading stops it."""
        entry = self.config_entry
        create = getattr(entry, "async_create_background_task", None)
        if create is None:  # no entry to bind to (tests, very old Home Assistant)
            self.hass.async_create_task(coro)
            return
        task = create(self.hass, coro, f"{DOMAIN} intraday job")
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    async def async_stop_jobs(self) -> None:
        """Cancel the side jobs and wait until they have stopped (the entry is being unloaded)."""
        jobs = [task for task in self._jobs if not task.done()]
        for task in jobs:
            task.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    async def _skip(self, key: str, results: dict[str, Any]) -> bool:
        if key == "summary":
            return False
        if "summary" not in results or results["summary"] is None:
            return self._last_full is not None  # no summary: connectivity trouble, do not pile on
        if (self.data or {}).get("_day") != self._cycle_day.isoformat():
            return False  # first cycle of a new day: refresh everything, keep nothing of yesterday
        sync = dig(results["summary"], "lastSyncTimestampGMT")
        changed = sync is not None and sync != self._last_sync
        due = self._last_full is None or dt_util.utcnow() - self._last_full >= DAILY_FULL_REFRESH
        return not (changed or due)

    async def _after_update(self, results: dict[str, Any], skipped: bool) -> None:
        sync = dig(results.get("summary"), "lastSyncTimestampGMT")
        # The last sync time seen so far travels with the data: right after midnight the new
        # day's summary has none yet, and entities still need to know when the watch last synced.
        if sync is None and results.get("summary") is None:
            results["_last_sync"] = self._last_sync
            return
        # A missing sync time (e.g. right after midnight) must not erase the last known one,
        # otherwise the first real sync of the day would not count as a change. Only the very
        # first cycle after the start is no change (the followers refresh on their own then).
        primed_before = self._primed
        changed = sync is not None and primed_before and sync != self._last_sync
        # A sync that follows one from before today's midnight may carry the evening of yesterday.
        late_sync = changed and self._sync_before_today(self._last_sync, self._cycle_day)
        if sync is not None:
            self._last_sync = sync
        if not skipped:
            self._last_full = dt_util.utcnow()
        self._primed = True
        results["_last_sync"] = self._last_sync
        day = self._cycle_day
        if (self._hourly_stats or self._history_auto) and not skipped and (changed or not primed_before or self._intraday_day != day):
            # After a new sync, at the first full refresh after a start and on a new day. In the
            # background: the entities must not wait for the extra requests.
            self._intraday_day = day
            fetched = {key: results[key] for key in SERIES if key in results}
            self._start_job(self.async_write_hourly_statistics(day, fetched, changed, late_sync))
        if changed:
            _LOGGER.debug("New watch sync %s: refreshing follower groups", sync)
            for follower in self.followers:
                self.hass.async_create_task(follower.async_request_refresh())

    @staticmethod
    def _sync_before_today(previous: Any, day: date) -> bool:
        """Whether the previous watch sync is known and lies before the start of ``day``."""
        before = parse_timestamp(previous)
        return before is not None and before < dt_util.start_of_local_day(day)

    async def async_write_hourly_statistics(
        self, day: date, fetched: Mapping[str, Any], changed: bool, late_sync: bool = False
    ) -> None:
        """Write the closed hours of today (and of yesterday) as hourly statistics; never raises.

        ``fetched`` holds the series this cycle already asked for (they are reused); every other
        series costs one request. Yesterday is added on the first run of a day, after new syncs in the
        morning and after the first sync that follows one from before midnight (``late_sync``; one request
        per series). Runs one at a time.
        """
        if self._intraday_lock is None:
            self._intraday_lock = asyncio.Lock()
        async with self._intraday_lock:
            try:
                await self._write_hourly(day, fetched, changed, late_sync)
            except GarminRateLimitError as err:
                _LOGGER.debug("Hourly statistics: Garmin limits requests, trying again at the next sync: %s", err)
            except GarminError as err:
                _LOGGER.debug("Hourly statistics: request failed: %s", err)
            except Exception as err:  # a side job must never break the update
                _LOGGER.warning("Hourly statistics could not be written: %s", err)

    async def _write_hourly(
        self, day: date, fetched: Mapping[str, Any], changed: bool, late_sync: bool = False
    ) -> None:
        """The job behind every trigger: hourly statistics and/or history states from the same requests."""
        entry = self.config_entry
        if entry is None:
            return
        now = dt_util.utcnow()
        manager = manager_for(self.hass, entry) if self._history_auto else None
        active: list[str] = []
        if manager is not None:
            active = await manager.active_series()
            manager.ensure_backfill(self.api)  # gaps between the keep limit and yesterday, in the background
        want_yesterday = (
            self._yesterday_done != day
            or late_sync
            or (changed and dt_util.now().hour < YESTERDAY_RETRY_UNTIL_HOUR)
        )
        yesterday_complete = want_yesterday
        for key, spec in HISTORY_SERIES.items():
            if not (self._hourly_stats and key in SERIES) and key not in active:
                continue
            try:
                today_payload = fetched[key] if key in fetched else await fetch_series(self.api, key, day)
            except GarminRateLimitError:
                raise
            except GarminError as err:
                yesterday_complete = False  # try this series again next time
                _LOGGER.debug("Intraday job: %s failed: %s", key, err)
                continue
            today_points = spec.parse(today_payload)
            yesterday_points: list | None = None
            first_day = day
            if want_yesterday:
                try:
                    yesterday_points = spec.parse(await fetch_series(self.api, key, day - timedelta(days=1)))
                    first_day = day - timedelta(days=1)
                except GarminRateLimitError:
                    raise
                except GarminError as err:
                    yesterday_complete = False
                    _LOGGER.debug("Intraday job: yesterday's %s failed: %s", key, err)
            if today_points is None or yesterday_points is None and first_day != day:
                note_unknown_format(key)
            if self._hourly_stats and key in SERIES:
                points = merge_points(*(p for p in (yesterday_points, today_points) if p))
                hours = drop_straddling(
                    closed_hours(hourly_aggregate(points), now),
                    dt_util.start_of_local_day(first_day),
                    dt_util.start_of_local_day(day + timedelta(days=1)),
                )
                write_hourly(self.hass, entry.entry_id, entry.title, spec.stat_name, spec.unit, hours)
            if manager is not None and key in active:
                await self._append_history(manager, key, day, yesterday_points, today_points)
        if yesterday_complete:
            self._yesterday_done = day

    async def _append_history(
        self, manager: Any, key: str, day: date, yesterday_points: list | None, today_points: list | None
    ) -> None:
        """Append the points never written before (yesterday first, then today); never today as "done"."""
        async with manager.lock, manager.persisting():
            ledger = await manager.ledger()
            for point_day, points in ((day - timedelta(days=1), yesterday_points), (day, today_points)):
                if not points:
                    continue
                result = await append_points(self.hass, self.config_entry, ledger, key, point_day, points)
                if result.error or result.unverified:
                    _LOGGER.debug("History states of %s not written: %s", key, result.error or "recorder not readable")
                    break
                manager.publish_latest(key, points)  # all of them are in the recorder now
            await manager.save()


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
            last = (stored or {}).get("last_id")
            # 0 was written by older versions after an empty first answer; it would make every
            # activity "new" once the list fills, so it counts as "nothing seen yet".
            self._last_id = last if isinstance(last, int) and last > 0 else None
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
        # An empty or missing answer never sets the baseline: that could be a hiccup (204,
        # error), and the next full list would then be reported as 20 new activities.
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
