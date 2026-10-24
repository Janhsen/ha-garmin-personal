"""Hourly statistics and history points from Garmin's intraday series (no Home Assistant imports).

Garmin delivers the day's heart rate, Body Battery and SpO2 as lists of measurements with a
timestamp in epoch milliseconds (UTC). The functions here turn such an answer into measuring
points and then into one minimum, maximum and mean per full UTC hour. Nothing is invented: an
hour without a measurement has no entry, nothing is interpolated or filled, and only the real
points of an hour are averaged (a plain mean of the measurements, not weighted by time).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple

from .values import to_number

_LOGGER = logging.getLogger(__name__)

HOUR_MS = 3_600_000
# Timestamps below this (1973) are not epoch milliseconds (seconds, counters, zero) and are dropped
# instead of being guessed; above the upper bound ``datetime`` would overflow.
_MIN_TS_MS = 100_000_000_000
_MAX_TS_MS = 4_000_000_000_000

# A measuring point: (epoch milliseconds UTC, value).
Point = tuple[int, float]


class HourStat(NamedTuple):
    """Minimum, maximum and mean of the measurements in one hour."""

    minimum: float
    maximum: float
    mean: float
    count: int


@dataclass(frozen=True)
class SeriesSpec:
    """One intraday series: statistic name, unit, and how to read Garmin's answer."""

    key: str  # name of the series (also the key the daily coordinator uses)
    stat_name: str  # statistic id suffix (``garmin_personal:<entry>_<stat_name>``)
    unit: str
    parse: Callable[[Any], list[Point] | None]


def _finite(value: Any) -> float | None:
    number = to_number(value)
    if number is None or not math.isfinite(number):
        return None
    return float(number)


def _timestamp(value: Any) -> int | None:
    number = _finite(value)
    if number is None or not _MIN_TS_MS <= number <= _MAX_TS_MS:
        return None
    return int(number)


def _pairs(rows: Any, ts_col: int, value_col: int, *, keep: Callable[[float], bool]) -> list[Point]:
    """``[[ts, ..., value, ...], ...]`` as points; rows that are broken or not ``keep`` are skipped."""
    points: list[Point] = []
    if not isinstance(rows, list):
        return points
    for row in rows:
        if not isinstance(row, list | tuple) or len(row) <= max(ts_col, value_col):
            continue
        ts, value = _timestamp(row[ts_col]), _finite(row[value_col])
        if ts is not None and value is not None and keep(value):
            points.append((ts, value))
    return points


def _descriptor_index(descriptors: Any, wanted: tuple[str, ...]) -> int | None:
    """The column of a descriptor (``{"...Key": name, "...Index": n}``) whose key is one of ``wanted``."""
    if not isinstance(descriptors, list):
        return None
    for descriptor in descriptors:
        if not isinstance(descriptor, Mapping):
            continue
        key = next((v for k, v in descriptor.items() if str(k).lower().endswith("key")), None)
        if isinstance(key, str) and key.lower() in wanted:
            for name, raw in descriptor.items():
                if str(name).lower().endswith("index"):
                    number = to_number(raw)
                    return int(number) if number is not None and number >= 0 else None
    return None


def heart_rate_points(payload: Any) -> list[Point] | None:
    """Points of ``dailyHeartRate``: ``heartRateValues`` = ``[[timestamp_ms, bpm], ...]``.

    ``None`` if the answer has an unknown shape; an empty list if there are no measurements.
    Zero and negative values are placeholders, not a heart rate.
    """
    if payload is None:
        return []
    if not isinstance(payload, Mapping) or "heartRateValues" not in payload:
        return None
    rows = payload["heartRateValues"]
    if rows is None:
        return []
    if not isinstance(rows, list):
        return None
    descriptors = payload.get("heartRateValueDescriptors")
    ts_col = _descriptor_index(descriptors, ("timestamp",))
    value_col = _descriptor_index(descriptors, ("heartrate",))
    return _pairs(rows, 0 if ts_col is None else ts_col, 1 if value_col is None else value_col,
                  keep=lambda v: v > 0)


def body_battery_points(payload: Any) -> list[Point] | None:
    """Points of the Body Battery report (a list with one report per day, or one report).

    The column of the level is looked up in Garmin's descriptor list; without it there is
    no series (a column is never guessed). Negative values are placeholders; 0 is a real level.
    """
    if payload is None:
        return []
    reports = payload if isinstance(payload, list) else [payload]
    points: list[Point] = []
    for report in reports:
        if report is None:
            continue
        if not isinstance(report, Mapping) or "bodyBatteryValuesArray" not in report:
            return None
        rows = report["bodyBatteryValuesArray"]
        if rows is None:
            continue
        descriptors = report.get("bodyBatteryValueDescriptorDTOList")
        ts_col = _descriptor_index(descriptors, ("timestamp",))
        level_col = _descriptor_index(descriptors, ("bodybatterylevel",))
        if level_col is None:
            return None
        points.extend(_pairs(rows, 0 if ts_col is None else ts_col, level_col, keep=lambda v: v >= 0))
    return points


def spo2_points(payload: Any) -> list[Point] | None:
    """Points of the SpO2 answer: ``spO2HourlyAverages`` = ``[[timestamp_ms, spo2Level, environment], ...]``.

    The columns come from Garmin's descriptor list (``spO2HourlyAveragesDescriptorList``); without a
    usable descriptor the classic layout applies (timestamp, then percent). The environment column
    is not SpO2 and is never read. Garmin only reports hourly averages here, so minimum, maximum and
    mean of such an hour are the same value. Zero, negative and ``null`` values are placeholders.
    """
    if payload is None:
        return []
    if not isinstance(payload, Mapping) or "spO2HourlyAverages" not in payload:
        return None
    rows = payload["spO2HourlyAverages"]
    if rows is None:
        return []
    if not isinstance(rows, list):
        return None
    descriptors = payload.get("spO2HourlyAveragesDescriptorList")
    ts_col = _descriptor_index(descriptors, ("timestamp",))
    value_col = _descriptor_index(descriptors, ("spo2level",))
    return _pairs(rows, 0 if ts_col is None else ts_col, 1 if value_col is None else value_col,
                  keep=lambda v: v > 0)


def _utc_ms(value: Any) -> int | None:
    """An ISO time (``2026-10-23T01:05:00.0``) as epoch milliseconds; without a zone it is UTC."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return _timestamp(round(moment.timestamp() * 1000))


def hrv_points(payload: Any) -> list[Point] | None:
    """Points of the nightly HRV answer: ``hrvReadings`` = ``[{hrvValue, readingTimeGMT, ...}, ...]``.

    Only ``readingTimeGMT`` is used for the time (UTC; ``readingTimeLocal`` is a wall-clock time and
    never read). ``None`` for an unknown shape, an empty list if there are no readings (an answer
    with only the night's summary counts as such). Zero and negative values are placeholders; low
    values next to high ones are real measurements and stay.
    """
    if payload is None:
        return []
    if not isinstance(payload, Mapping):
        return None
    if "hrvReadings" not in payload:
        return [] if "hrvSummary" in payload else None
    rows = payload["hrvReadings"]
    if rows is None:
        return []
    if not isinstance(rows, list):
        return None
    points: list[Point] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        ts, value = _utc_ms(row.get("readingTimeGMT")), _finite(row.get("hrvValue"))
        if ts is not None and value is not None and value > 0:
            points.append((ts, value))
    return points


SERIES: dict[str, SeriesSpec] = {
    "heart_rate": SeriesSpec("heart_rate", "heart_rate_hourly", "bpm", heart_rate_points),
    "body_battery": SeriesSpec("body_battery", "body_battery_hourly", "%", body_battery_points),
    "spo2": SeriesSpec("spo2", "spo2_hourly", "%", spo2_points),
}


# What the history sensors can carry: the hourly-statistics series and the night's HRV (no statistic: its
# readings exist for the night only and a statistic would cost one more request on every sync).
HISTORY_SERIES: dict[str, SeriesSpec] = {
    **SERIES,
    "hrv": SeriesSpec("hrv", "hrv_hourly", "ms", hrv_points),
}


def hour_start(ts_ms: int) -> datetime:
    """The full UTC hour a timestamp (epoch milliseconds) falls into."""
    return datetime.fromtimestamp(ts_ms // HOUR_MS * 3600, tz=UTC)


def hourly_aggregate(points: list[Point]) -> dict[datetime, HourStat]:
    """Minimum, maximum, mean and number of points per full UTC hour; hours without points are absent."""
    buckets: dict[int, list[float]] = {}
    for ts, value in points:
        buckets.setdefault(ts // HOUR_MS, []).append(value)
    return {
        datetime.fromtimestamp(bucket * 3600, tz=UTC): HourStat(
            min(values), max(values), math.fsum(values) / len(values), len(values)
        )
        for bucket, values in sorted(buckets.items())
    }


def closed_hours(hours: dict[datetime, HourStat], now: datetime) -> dict[datetime, HourStat]:
    """Only hours that are over: the running hour is incomplete and must not be stored."""
    return {start: stat for start, stat in hours.items() if start + timedelta(hours=1) <= now}


def hours_from_payload(spec: SeriesSpec, payload: Any, now: datetime) -> dict[datetime, HourStat] | None:
    """Closed hours of one Garmin answer; ``None`` if the answer's shape is unknown."""
    points = spec.parse(payload)
    if points is None:
        return None
    return closed_hours(hourly_aggregate(points), now)


def merge_points(*series: list[Point]) -> list[Point]:
    """Points of several answers (for example two days) as one list; a timestamp counts once.

    Needed because an hour can reach into two days when the time zone's offset is not a whole
    number of hours: that hour is only right if both halves are averaged together.
    """
    seen: dict[int, float] = {}
    for points in series:
        for ts, value in points:
            seen.setdefault(ts, value)
    return sorted(seen.items())


def drop_straddling(hours: dict[datetime, HourStat], *boundaries: datetime) -> dict[datetime, HourStat]:
    """Remove hours that contain one of the boundaries (where the fetched days end).

    With whole-hour time zones no hour straddles a day boundary and nothing is removed. In a zone
    like +05:30 the hour around local midnight would be built from one half only, so it is left
    out instead of being stored wrong.
    """
    hour = timedelta(hours=1)
    return {
        start: stat
        for start, stat in hours.items()
        if not any(start < boundary < start + hour for boundary in boundaries)
    }


_WARNED_FORMATS: set[str] = set()


def note_unknown_format(key: str) -> None:
    """One info line per series and run: Garmin's answer had a shape this version does not read."""
    if key not in _WARNED_FORMATS:
        _WARNED_FORMATS.add(key)
        _LOGGER.info("Garmin %s answer has an unknown format; no hourly statistics for it", key)


async def fetch_series(api: Any, key: str, day: date) -> Any:
    """Ask Garmin for one series of one day (one request)."""
    fetchers: dict[str, Callable[[], Awaitable[Any]]] = {
        "heart_rate": lambda: api.get_heart_rate(day),
        "body_battery": lambda: api.get_body_battery(day, day),
        "spo2": lambda: api.get_spo2(day),
        "hrv": lambda: api.get_hrv(day),
    }
    return await fetchers[key]()
