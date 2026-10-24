"""History entities: measuring points as recorder states with their real timestamps (scaffold).

The plan: a separate sensor per series (``*_history``, disabled by default) whose recorded states are
the real Garmin measurements, each at its own time, so that the History panel can show them. The live
sensors never receive old values.

Writing states with a past ``last_updated`` is not possible through Home Assistant's public API: the
state machine always stamps "now", and ``hass.states.async_set`` fires ``state_changed`` for every
listener (automations, logbook, websocket clients). The only path that reaches the recorder alone is
to put a hand-built ``state_changed`` event on the recorder's own queue (``Recorder.queue_task``).
That is undocumented, depends on the recorder's internals (it reads ``old_state.last_reported_timestamp``
of the previous row, the ``Event``/``State`` constructors changed between versions, entity filters are
bypassed) and cannot be verified without a running Home Assistant. Until it is verified there,
``write_history_states`` refuses to write and the service reports ``history_write_unsupported``.
"""

from __future__ import annotations

import zlib
from datetime import date, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .intraday import Point

# series key (as in intraday.SERIES) -> translation key / unique id suffix of its history sensor
HISTORY_KEYS: dict[str, str] = {
    "heart_rate": "heart_rate_history",
    "body_battery": "body_battery_history",
    "spo2": "spo2_history",
}


# Set to True only after the recorder path described above has been verified on a real Home Assistant.
WRITE_SUPPORTED = False

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


async def write_history_states(hass: Any, entry: Any, series: str, points: list[Point]) -> int:
    """Write ``points`` as recorded states of the history sensor of ``series``; returns the number written.

    Not implemented on purpose, see the module docstring.
    """
    raise HistoryWriteUnsupported(series)


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
        start = dt_util.start_of_local_day(day)
        states = await get_instance(hass).async_add_executor_job(
            lambda: history.state_changes_during_period(
                hass, start, start + timedelta(days=1), entity_id, no_attributes=True, include_start_time_state=False
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
