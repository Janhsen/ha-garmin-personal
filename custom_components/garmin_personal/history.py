"""History sensors: measuring points as recorder states with their real timestamps.

A separate sensor per series (``*_history``, disabled by default) whose recorded states are the real
Garmin measurements, each at its own time, so that the History panel can show them. The live sensors
never receive old values.

Writing states with a past ``last_updated`` is not possible through Home Assistant's public API: the
state machine always stamps "now", and ``hass.states.async_set`` fires ``state_changed`` for every
listener (automations, logbook, websocket clients). The only path that reaches the recorder alone is
to put a hand-built ``state_changed`` event on the recorder's own queue (``Recorder.queue_task``).
That is undocumented and depends on the recorder's internals (it reads ``old_state.last_reported_timestamp``
of the previous row, the ``Event``/``State`` constructors changed between versions, entity filters are
bypassed, so they are checked here). It was verified on a real Home Assistant; every step is defensive
and a failed hand-over stops at once.

Writing is append-only. The ``Ledger`` decides "written already?" per series, day and timestamp.
"""

from __future__ import annotations

import asyncio
import logging
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .api import GarminAuthError, GarminError, GarminRateLimitError
from .const import DOMAIN
from .intraday import HISTORY_SERIES, Point, fetch_series, merge_points, note_unknown_format

_LOGGER = logging.getLogger(__name__)

# series key (as in intraday.SERIES) -> translation key / unique id suffix of its history sensor
HISTORY_KEYS: dict[str, str] = {
    "heart_rate": "heart_rate_history",
    "body_battery": "body_battery_history",
    "spo2": "spo2_history",
    "hrv": "hrv_history",
}


# Hand-over pauses: after this many events the loop yields, and above this recorder backlog it stops.
YIELD_EVERY = 100
MAX_RECORDER_BACKLOG = 20000

# Days with the exact written timestamps (and values) the ledger keeps; older days shrink to a mark.
LEDGER_DETAIL_DAYS = 7
# Upper bound of points kept per detail day (a heart rate day has about 720).
LEDGER_MAX_POINTS_PER_DAY = 5000


class HistoryWriteUnsupported(Exception):
    """States with historic timestamps cannot be written safely on this Home Assistant."""


def new_points(points: list[Point], last_written_ts: int | None) -> list[Point]:
    """The points still to be written: oldest first, one per timestamp, none at or before the last written one."""
    seen: dict[int, float] = {}
    for ts, value in points:
        if last_written_ts is None or ts > last_written_ts:
            seen.setdefault(ts, value)
    return sorted(seen.items())


class HistoryTargetError(Exception):
    """The history sensor cannot take states; ``key`` is the translation key of the error."""

    def __init__(self, key: str, entity_id: str = "") -> None:
        """Remember the translation key and the entity id for the message."""
        super().__init__(key)
        self.key = key
        self.entity_id = entity_id


def _unit_of(series: str) -> str:
    return {"heart_rate": "bpm", "hrv": "ms"}.get(series, "%")


def _state_text(value: float) -> str:
    return str(int(value)) if value == int(value) else repr(value)


async def check_target(hass: Any, entry: Any, series: str) -> str:
    """The entity id of the history sensor, if it exists, is enabled and the recorder records it.

    Raises ``HistoryTargetError`` (translated) otherwise, and ``HistoryWriteUnsupported`` if the
    registry or the recorder cannot be reached. Nothing is written or requested here.
    """
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{HISTORY_KEYS[series]}")
        reg_entry = registry.async_get(entity_id) if entity_id else None
        instance = get_instance(hass)
        entity_filter = getattr(instance, "entity_filter", None)
    except Exception as err:  # registry/recorder API differs between versions
        raise HistoryWriteUnsupported(str(err)) from err
    if entity_id is None or reg_entry is None:
        raise HistoryTargetError("history_sensor_missing")
    if getattr(reg_entry, "disabled_by", None) is not None:
        raise HistoryTargetError("history_sensor_disabled", entity_id)
    if entity_filter is not None and not entity_filter(entity_id):
        raise HistoryTargetError("history_not_recorded", entity_id)
    return entity_id


async def write_history_states(hass: Any, entry: Any, series: str, points: list[Point]) -> tuple[int, str | None]:
    """Put ``points`` into the recorder as states of the history sensor, at their own times.

    Returns ``(n, error)``: the first ``n`` points (oldest first) were handed over, ``error`` says why
    it stopped early (``None`` if all went through). It never raises for a failed hand-over, so the
    caller can note exactly the written points. Target problems raise ``HistoryTargetError`` before
    anything is written.

    Each point becomes a ``state_changed`` event with a state stamped at the measurement time and
    the previous point as ``old_state`` (the recorder reads its ``last_reported``), put on the
    recorder's own queue: no listener of the event bus ever sees it.
    """
    import asyncio

    from homeassistant.components.recorder import get_instance
    from homeassistant.const import EVENT_STATE_CHANGED
    from homeassistant.core import Event, State

    entity_id = await check_target(hass, entry, series)
    ordered = sorted(points)
    done = 0
    try:
        instance = get_instance(hass)
        attributes = {"unit_of_measurement": _unit_of(series)}
        previous = None
        for ts, value in ordered:
            when = dt_util.utc_from_timestamp(ts / 1000)
            state = State(
                entity_id, _state_text(value), attributes,
                last_changed=when, last_reported=when, last_updated=when,
            )
            event = Event(
                EVENT_STATE_CHANGED,
                {"entity_id": entity_id, "old_state": state if previous is None else previous, "new_state": state},
                time_fired_timestamp=ts / 1000,
            )
            instance.queue_task(event)
            previous = state
            done += 1
            if done % YIELD_EVERY == 0:
                await asyncio.sleep(0)
                if getattr(instance, "backlog", 0) > MAX_RECORDER_BACKLOG:
                    return done, "recorder queue is full"
    except Exception as err:  # stop at once; what was handed over is reported
        return done, str(err)
    return done, None


def _crc(ts: int, value: float) -> int:
    return zlib.crc32(f"{ts}:{value!r}".encode())


class Ledger:
    """Which points were written already: per series and day, never "the last timestamp" alone.

    Recent days keep every written timestamp with its value (a point is *same*, *changed* or *new*);
    older days keep a mark: count, first and last timestamp and an order-independent checksum.
    Points of a marked day inside first..last count as written, others as new. Days the ledger has
    never seen are *unknown*: the caller must check the recorder before writing anything there.
    Nothing is ever removed from what was written; an entry only grows.
    """

    VERSION = 1
    MAX_DONE_DAYS = 500

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        """Load from the dict a store returned (``None``/wrong version: a fresh, empty ledger)."""
        ok = isinstance(data, dict) and data.get("v") == self.VERSION and isinstance(data.get("series"), dict)
        self.data: dict[str, Any] = data if ok else {"v": self.VERSION, "series": {}}  # type: ignore[assignment]

    def _day(self, series: str, day: str) -> dict[str, Any] | None:
        entry = self.data["series"].get(series, {}).get(day)
        return entry if isinstance(entry, dict) else None

    def knows(self, series: str, day: str) -> bool:
        """Whether this day of this series has ever been recorded here."""
        return self._day(series, day) is not None

    def is_done(self, series: str, day: str) -> bool:
        """Whether the initial load has finished this (past) day of this series."""
        return day in self.data.get("done", {}).get(series, ())

    def mark_done(self, series: str, day: str) -> None:
        """Remember a finished past day (never today); the list is bounded."""
        days = self.data.setdefault("done", {}).setdefault(series, [])
        if day not in days:
            days.append(day)
            days.sort()
            del days[: max(0, len(days) - self.MAX_DONE_DAYS)]

    def oldest_contiguous_done(self, series: str, yesterday: date) -> str | None:
        """The oldest day of the unbroken run of finished days that ends at ``yesterday``."""
        oldest = None
        day = yesterday
        while self.is_done(series, day.isoformat()) and (yesterday - day).days <= self.MAX_DONE_DAYS:
            oldest = day.isoformat()
            day -= timedelta(days=1)
        return oldest

    def floor(self, series: str) -> str | None:
        """Day where the initial load once found nothing older (it does not look beyond again)."""
        value = self.data.get("floor", {}).get(series)
        return value if isinstance(value, str) else None

    def set_floor(self, series: str, day: str) -> None:
        """Remember where the initial load stopped for lack of data."""
        self.data.setdefault("floor", {})[series] = day

    def classify(
        self, series: str, day: str, points: list[Point]
    ) -> tuple[list[Point], int, int]:
        """(new points oldest first, number already written, number whose value differs from the written one)."""
        entry = self._day(series, day) or {}
        written = entry.get("p")
        new: dict[int, float] = {}
        same = changed = 0
        for ts, value in points:
            if isinstance(written, dict):
                old = written.get(str(ts))
                if old is None:
                    new.setdefault(ts, value)
                elif old == value:
                    same += 1
                else:
                    changed += 1
            elif entry and entry.get("lo") <= ts <= entry.get("hi"):
                same += 1  # a marked day cannot say more
            else:
                new.setdefault(ts, value)
        return sorted(new.items()), same, changed

    def record(self, series: str, day: str, points: list[Point]) -> None:
        """Note points as written (adds only; a timestamp already noted keeps its first value)."""
        days = self.data["series"].setdefault(series, {})
        entry = days.setdefault(day, {"p": {}})
        if "p" in entry:
            for ts, value in points:
                if len(entry["p"]) < LEDGER_MAX_POINTS_PER_DAY:
                    entry["p"].setdefault(str(ts), value)
        else:  # marked day
            for ts, value in points:
                if not entry["lo"] <= ts <= entry["hi"]:
                    entry["n"] += 1
                    entry["c"] = (entry["c"] + _crc(ts, value)) & 0xFFFFFFFF
                    entry["lo"], entry["hi"] = min(entry["lo"], ts), max(entry["hi"], ts)

    def compact(self, today: str) -> None:
        """Shrink days older than ``LEDGER_DETAIL_DAYS`` before ``today`` (ISO date) to a mark."""
        limit = (date.fromisoformat(today) - timedelta(days=LEDGER_DETAIL_DAYS)).isoformat()
        for days in self.data["series"].values():
            for day, entry in days.items():
                points = entry.get("p")
                if day < limit and isinstance(points, dict):
                    stamps = [int(t) for t in points]
                    days[day] = {
                        "n": len(stamps),
                        "lo": min(stamps, default=0),
                        "hi": max(stamps, default=0),
                        "c": sum(_crc(int(t), v) for t, v in points.items()) & 0xFFFFFFFF,
                    }


def series_window(series: str, day: Any) -> tuple[Any, Any]:
    """The time span of the recorder to look at for one ledger day of a series.

    Most series belong to their local calendar day. The HRV of a night belongs to the day of waking
    up, but its readings lie in the evening before and the morning of that day: noon to noon.
    """
    start = dt_util.start_of_local_day(day)
    if series == "hrv":
        return start - timedelta(hours=12), start + timedelta(hours=12)
    return start, start + timedelta(days=1)


async def recorded_points(hass: Any, entry: Any, series: str, day: Any) -> dict[int, float]:
    """Read-only: the states of the history sensor already in the recorder for one local day.

    Used when the ledger does not know the day (new install, lost store): what is already there
    counts as written. Raises ``HistoryWriteUnsupported`` if the recorder cannot be asked.
    """
    try:
        from homeassistant.components.recorder import get_instance, history
        from homeassistant.helpers import entity_registry as er

        entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{HISTORY_KEYS[series]}")
        if entity_id is None:
            raise HistoryWriteUnsupported("history sensor is not registered")
        start, end = series_window(series, day)
        states = await get_instance(hass).async_add_executor_job(
            lambda: history.state_changes_during_period(
                hass, start, end, entity_id, no_attributes=True, include_start_time_state=False
            )
        )
    except HistoryWriteUnsupported:
        raise
    except Exception as err:  # the recorder API differs between versions
        raise HistoryWriteUnsupported(str(err)) from err
    found: dict[int, float] = {}
    for state in states.get(entity_id, []):
        try:
            found[round(state.last_updated.timestamp() * 1000)] = float(state.state)
        except (TypeError, ValueError):
            continue
    return found


@dataclass
class AppendResult:
    """What happened to the points of one series and day."""

    written: int = 0
    already: int = 0
    changed: int = 0
    adopted: int = 0
    unverified: bool = False  # the day is unknown to the ledger and the recorder could not be read
    error: str | None = None


async def append_points(
    hass: Any, entry: Any, ledger: Ledger, series: str, day: date, points: list[Point], *, confirm: bool = False
) -> AppendResult:
    """Append the points of one day that were never written; the ledger decides, never a last timestamp.

    A day the ledger does not know is first looked up in the recorder (read only): what is there counts
    as written. If that is impossible nothing is written, unless ``confirm`` says to go ahead anyway.
    A changed value for a known timestamp is counted, not written.
    """
    result = AppendResult()
    points = merge_points(points)
    if not points:
        return result
    iso = day.isoformat()
    if not ledger.knows(series, iso):
        try:
            found = await recorded_points(hass, entry, series, day)
        except HistoryWriteUnsupported:
            if not confirm:
                result.unverified = True
                return result
        else:
            if found:
                ledger.record(series, iso, sorted(found.items()))
                result.adopted = len(found)
    new, result.already, result.changed = ledger.classify(series, iso, points)
    if new:
        try:
            done, result.error = await write_history_states(hass, entry, series, new)
        except HistoryTargetError as err:
            done, result.error = 0, err.key
        result.written = done
        ledger.record(series, iso, new[:done])  # only what was really handed over
    return result


def recorder_keep_days(hass: Any) -> int:
    """How many days the recorder keeps (``purge_keep_days``); 10 if unknown, never more than 400."""
    try:
        from homeassistant.components.recorder import get_instance

        value = get_instance(hass).keep_days
    except Exception:  # no recorder or a version without the attribute
        value = None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        value = 10
    return min(value, MAX_BACKFILL_DAYS)


class HistoryManager:
    """Per account: the shared ledger, one lock, the initial load in the background and its progress.

    The lock is shared with the backfill services, so an initial load never runs in parallel to them;
    it is held only for one day at a time so a service can step in between.
    """

    def __init__(self, hass: Any, entry: Any) -> None:
        """Set up; the ledger is loaded on first use."""
        from homeassistant.helpers.storage import Store

        self.hass, self.entry = hass, entry
        self.lock = asyncio.Lock()
        self.throttle_s = BACKFILL_THROTTLE_S
        self.rate_pause_s = BACKFILL_RATE_PAUSE_S
        self.sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep
        self.progress: dict[str, dict[str, str]] = {}
        self.listeners: dict[str, Callable[[], None]] = {}
        self.latest_listeners: dict[str, Callable[[int, float], None]] = {}
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.history_ledger")
        self._ledger: Ledger | None = None
        self._task: Any = None

    async def ledger(self) -> Ledger:
        """The account's ledger (loaded once)."""
        if self._ledger is None:
            self._ledger = Ledger(await self._store.async_load())
        return self._ledger

    async def save(self) -> None:
        """Write the ledger to disk."""
        if self._ledger is not None:
            self._ledger.compact(dt_util.now().date().isoformat())
            await self._store.async_save(self._ledger.data)

    async def active_series(self) -> list[str]:
        """Series whose history sensor is enabled and recorded; checked fresh each time.

        An enabled sensor the recorder does not record gets a repair issue, everything else stays silent.
        """
        from .repairs import update_history_issue

        active = []
        for series in HISTORY_KEYS:
            excluded = False
            try:
                await check_target(self.hass, self.entry, series)
                active.append(series)
            except HistoryTargetError as err:
                excluded = err.key == "history_not_recorded"
                _LOGGER.debug("History sensor of %s not used: %s", series, err.key)
            except HistoryWriteUnsupported as err:
                _LOGGER.debug("History sensor of %s not used: %s", series, err)
            update_history_issue(self.hass, self.entry, series, excluded)
        return active

    def publish_latest(self, series: str, points: list[Point]) -> None:
        """Tell the history sensor the newest point of the live filling; never raises.

        Only the forward path calls this (never the initial load or a service run for old days).
        The sensor itself ignores a point that is not newer than the one it shows.
        """
        listener = self.latest_listeners.get(series)
        if listener is None or not points:
            return
        ts, value = max(points)
        try:
            listener(ts, value)
        except Exception as err:  # a display problem must not stop the job
            _LOGGER.debug("History value could not be shown: %s", err)

    def _notify(self, series: str) -> None:
        listener = self.listeners.get(series)
        if listener is not None:
            try:
                listener()
            except Exception as err:  # a display problem must not stop the load
                _LOGGER.debug("History progress could not be shown: %s", err)

    async def _refresh_progress(self, series: str, ledger: Ledger) -> None:
        yesterday = dt_util.now().date() - timedelta(days=1)
        until = ledger.oldest_contiguous_done(series, yesterday) or ledger.floor(series)
        new = {"history_backfilled_until": until} if until else {}
        if new != self.progress.get(series, {}):
            self.progress[series] = new
            self._notify(series)

    def ensure_backfill(self, api: Any) -> None:
        """Start the initial load in the background unless it is running; it fills every gap per series."""
        if self._task is not None and not self._task.done():
            return
        coro = self.run_backfill(api)
        try:
            self._task = self.entry.async_create_background_task(self.hass, coro, f"{DOMAIN} history load")
        except Exception as err:  # no task could be started: nothing to do now, the next trigger tries again
            coro.close()
            _LOGGER.debug("History load not started: %s", err)

    async def run_backfill(self, api: Any) -> None:
        """Fill the past days of every active series, newest first; never raises."""
        try:
            for series in await self.active_series():
                await self._backfill_series(api, series)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # a side job must never break anything
            _LOGGER.warning("History load stopped: %s", err)

    async def _backfill_series(self, api: Any, series: str) -> None:
        ledger = await self.ledger()
        today = dt_util.now().date()
        oldest = today - timedelta(days=recorder_keep_days(self.hass))
        floor = ledger.floor(series)
        day = today - timedelta(days=1)
        empty = failures = 0
        while day >= oldest and not (floor and day.isoformat() <= floor):
            iso = day.isoformat()
            if ledger.is_done(series, iso):
                day -= timedelta(days=1)
                continue
            try:
                await check_target(self.hass, self.entry, series)  # fresh before each day
            except (HistoryTargetError, HistoryWriteUnsupported):
                break
            try:
                async with self.lock:
                    payload = await fetch_series(api, series, day)
                    parsed = HISTORY_SERIES[series].parse(payload)
                    if parsed is None:
                        note_unknown_format(series)
                        break
                    result = await append_points(self.hass, self.entry, ledger, series, day, parsed)
                    await self.save()
            except GarminRateLimitError:
                _LOGGER.debug("History load: Garmin limits requests, pausing")
                await self.sleep(self.rate_pause_s)
                continue
            except GarminAuthError:
                break
            except GarminError as err:
                failures += 1
                _LOGGER.debug("History load: %s failed for a day: %s", series, err)
                if failures >= 3:
                    break
                await self.sleep(self.throttle_s)
                continue
            if result.error or result.unverified:
                _LOGGER.debug("History load stopped for %s: %s", series, result.error or "recorder not readable")
                break
            failures = 0
            ledger.mark_done(series, iso)
            await self.save()
            empty = 0 if parsed else empty + 1
            if empty >= BACKFILL_EMPTY_STOP:
                ledger.set_floor(series, iso)
                await self.save()
                break
            day -= timedelta(days=1)
            await self.sleep(self.throttle_s)
        await self._refresh_progress(series, ledger)


# Initial load: one day request per this many seconds, a pause after a rate limit, the cap in days and
# the number of empty days in a row after which it stops looking further back.
BACKFILL_THROTTLE_S = 20
BACKFILL_RATE_PAUSE_S = 1800
MAX_BACKFILL_DAYS = 400
BACKFILL_EMPTY_STOP = 14


def manager_for(hass: Any, entry: Any) -> HistoryManager:
    """The account's ``HistoryManager`` (created on first use, kept on the runtime data)."""
    runtime = entry.runtime_data
    manager = getattr(runtime, "history", None)
    if manager is None:
        manager = HistoryManager(hass, entry)
        runtime.history = manager
    return manager
