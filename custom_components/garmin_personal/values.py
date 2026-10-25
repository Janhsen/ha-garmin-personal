"""Pure helpers to pick values out of Garmin's JSON (no Home Assistant imports)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

ValueFn = Callable[[Mapping[str, Any]], Any]


def dig(data: Any, *path: str | int) -> Any:
    """Follow ``path`` through nested dicts/lists; ``None`` if anything is missing."""
    current = data
    for step in path:
        if current is None:
            return None
        if isinstance(step, int):
            if isinstance(current, Sequence) and not isinstance(current, str | bytes):
                try:
                    current = current[step]
                except IndexError:
                    return None
            else:
                return None
        elif isinstance(current, Mapping):
            current = current.get(step)
        else:
            return None
    return current


def to_number(value: Any) -> float | int | None:
    """Return ``value`` as a number, or ``None`` (booleans and strings are not numbers)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return value
    return None


# Only a long digit string counts as epoch milliseconds (13 digits today); a shorter one could
# be seconds or a compact date and is left alone.
_EPOCH_TEXT = re.compile(r"\d{12,}(\.\d+)?")


def parse_timestamp(value: Any) -> datetime | None:
    """Parse Garmin timestamps: epoch milliseconds or ISO strings, as UTC.

    Garmin's ``*GMT`` fields are UTC wall-clock times without an offset.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        if _EPOCH_TEXT.fullmatch(text):
            # Garmin types some timestamps (sleep start/end) as strings holding epoch milliseconds.
            return parse_timestamp(float(text))
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def finish_number(
    number: float | int,
    *,
    scale: float | None = None,
    digits: int | None = None,
    allow_negative: bool = False,
    zero_is_none: bool = False,
) -> float | int | None:
    """Scale and round one number the same way for every sensor.

    Negative values are Garmin placeholders (for example -1 for "no stress value", or
    negative calories from imported days) unless ``allow_negative``; with ``zero_is_none``
    a 0 means "not measured". ``digits=0`` gives an ``int`` (never ``90.0``).
    """
    if (number < 0 and not allow_negative) or (zero_is_none and number == 0):
        return None
    if scale:
        number = number / scale
    if digits is not None:
        number = round(number, digits)
        if digits == 0:
            number = int(number)
    return number


def number_at(
    *path: str | int,
    scale: float | None = None,
    digits: int | None = None,
    allow_negative: bool = False,
    zero_is_none: bool = False,
) -> ValueFn:
    """Value function: a number at ``path``, optionally divided by ``scale``."""

    def value(data: Mapping[str, Any]) -> float | int | None:
        number = to_number(dig(data, *path))
        if number is None:
            return None
        return finish_number(number, scale=scale, digits=digits, allow_negative=allow_negative,
                             zero_is_none=zero_is_none)

    return value


def text_at(*path: str | int) -> ValueFn:
    """Value function: a short string at ``path`` (Home Assistant limits states to 255)."""

    def value(data: Mapping[str, Any]) -> str | None:
        raw = dig(data, *path)
        if raw is None or isinstance(raw, Mapping | list):
            return None
        return str(raw)[:255]

    return value


def timestamp_at(*path: str | int) -> ValueFn:
    """Value function: a timestamp at ``path`` as a timezone-aware datetime."""

    def value(data: Mapping[str, Any]) -> datetime | None:
        return parse_timestamp(dig(data, *path))

    return value


# Entries Garmin creates itself when the profile weight is edited are not weighings.
NOT_A_WEIGHING = ("USER_SETTING", "CHANGE_LOG")


def is_weighing(entry: Mapping[str, Any]) -> bool:
    """Whether a ``DateWeight`` entry is a real weighing (manual entry or a scale)."""
    return str(entry.get("sourceType") or "").upper() not in NOT_A_WEIGHING


def latest_weight(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The newest real weighing (``DateWeight``) from a ``weight_range`` response.

    Profile edits (``USER_SETTING``, ``CHANGE_LOG``) are skipped, like in the statistics backfill.
    """
    summaries = dig(data, "weight", "dailyWeightSummaries")
    if not isinstance(summaries, list):
        return None
    candidates = [
        item
        for item in summaries
        if isinstance(item, Mapping) and isinstance(item.get("latestWeight"), Mapping)
        and is_weighing(item["latestWeight"])
    ]
    if not candidates:
        return None
    newest = max(candidates, key=lambda item: str(item.get("summaryDate") or ""))
    return newest["latestWeight"]


def weight_at(
    key: str, *, scale: float | None = None, digits: int | None = None, zero_is_none: bool = False
) -> ValueFn:
    """Value function: one field of the newest weighing."""

    def value(data: Mapping[str, Any]) -> float | int | None:
        entry = latest_weight(data)
        number = to_number(entry.get(key)) if entry else None
        if number is None:
            return None
        return finish_number(number, scale=scale, digits=digits, zero_is_none=zero_is_none)

    return value


def default_hr_zones(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The default sport's heart rate zones (or the first entry) from ``hr_zones``."""
    zones = data.get("hr_zones")
    if not isinstance(zones, list) or not zones:
        return None
    for entry in zones:
        if isinstance(entry, Mapping) and str(entry.get("sport", "")).upper() == "DEFAULT":
            return entry
    first = zones[0]
    return first if isinstance(first, Mapping) else None


def hr_zone_at(key: str) -> ValueFn:
    """Value function: one field of the default heart rate zones."""

    def value(data: Mapping[str, Any]) -> float | int | None:
        zones = default_hr_zones(data)
        number = to_number(zones.get(key)) if zones else None
        if number is None:
            # Some values exist only in one sport profile (e.g. lactate threshold in RUNNING).
            for entry in data.get("hr_zones") or []:
                if isinstance(entry, Mapping):
                    number = to_number(entry.get(key))
                    if number is not None:
                        break
        return number

    return value


def last_item(data: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    """The last element of a list stored under ``key`` (e.g. the newest HRV summary)."""
    items = data.get(key)
    if isinstance(items, list) and items and isinstance(items[-1], Mapping):
        return items[-1]
    return None


def first_item(data: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    """The first element of a list stored under ``key`` (e.g. the newest activity)."""
    items = data.get(key)
    if isinstance(items, list) and items and isinstance(items[0], Mapping):
        return items[0]
    return None


def latest_hrv(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The newest HRV summary that has a night average (by ``calendarDate``, not list position).

    Value and attributes must come from the same entry, so a day without a night
    average (for example today, before the watch has synced) is skipped as a whole.
    """
    items = data.get("hrv_summaries")
    if not isinstance(items, list):
        return None
    candidates = [
        (str(item.get("calendarDate") or ""), index, item)
        for index, item in enumerate(items)
        if isinstance(item, Mapping) and to_number(item.get("lastNightAvg")) is not None
    ]
    return max(candidates, key=lambda c: (c[0], c[1]))[2] if candidates else None


def fitness_age_item(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The fitness age record from the ``fitness_age`` answer, whichever shape Garmin sends.

    Garmin's specification describes a list of records, earlier answers were a single object:
    both are accepted. From a list, the record with the newest ``lastUpdated`` that has a
    fitness age is taken (the last one if no time can be read), else the last record.
    """
    raw = data.get("fitness_age")
    if isinstance(raw, Mapping):
        return raw
    if not isinstance(raw, list):
        return None
    records = [(index, item) for index, item in enumerate(raw) if isinstance(item, Mapping)]
    if not records:
        return None
    measured = [(i, item) for i, item in records if to_number(item.get("fitnessAge")) is not None]

    def newest(entry: tuple[int, Mapping[str, Any]]) -> tuple[float, int]:
        stamp = parse_timestamp(entry[1].get("lastUpdated"))
        return (stamp.timestamp() if stamp else float("-inf"), entry[0])

    return max(measured or records, key=newest)[1]


def fitness_age_at(key: str, *, digits: int | None = None) -> ValueFn:
    """Value function: one number of the fitness age record."""

    def value(data: Mapping[str, Any]) -> float | int | None:
        item = fitness_age_item(data)
        number = to_number(item.get(key)) if item else None
        return None if number is None else finish_number(number, digits=digits)

    return value


def item_number(group: str, key: str, *, scale: float | None = None, digits: int | None = None) -> ValueFn:
    """Value function: a number from the last element of ``data[group]``."""

    def value(data: Mapping[str, Any]) -> float | int | None:
        item = last_item(data, group)
        number = to_number(item.get(key)) if item else None
        if number is None:
            return None
        return finish_number(number, scale=scale, digits=digits)

    return value


def activity_number(
    *path: str | int, scale: float | None = None, digits: int | None = None, zero_is_none: bool = False
) -> ValueFn:
    """Value function: a number from the newest activity."""

    def value(data: Mapping[str, Any]) -> float | int | None:
        activity = first_item(data, "activities")
        number = to_number(dig(activity, *path)) if activity else None
        if number is None:
            return None
        return finish_number(number, scale=scale, digits=digits, zero_is_none=zero_is_none)

    return value


def activity_text(*path: str | int) -> ValueFn:
    """Value function: a string from the newest activity."""

    def value(data: Mapping[str, Any]) -> str | None:
        activity = first_item(data, "activities")
        raw = dig(activity, *path) if activity else None
        return None if raw is None or isinstance(raw, Mapping | list) else str(raw)[:255]

    return value


def activity_timestamp(*path: str | int) -> ValueFn:
    """Value function: a timestamp from the newest activity."""

    def value(data: Mapping[str, Any]) -> datetime | None:
        activity = first_item(data, "activities")
        return parse_timestamp(dig(activity, *path)) if activity else None

    return value


def series_pairs(rows: Any, value_index: int = 1) -> list[list[float]]:
    """Reduce Garmin's ``[[timestamp_ms, value, ...], ...]`` rows to ``[ts, value]`` pairs."""
    pairs: list[list[float]] = []
    if not isinstance(rows, list):
        return pairs
    for row in rows:
        if isinstance(row, list) and len(row) > value_index:
            timestamp, value = to_number(row[0]), to_number(row[value_index])
            if timestamp is not None and value is not None:
                pairs.append([timestamp, value])
    return pairs


def first_number(data: Any, *paths: tuple[str | int, ...]) -> float | int | None:
    """The first path that holds a number (used where Garmin's shapes differ)."""
    for path in paths:
        number = to_number(dig(data, *path))
        if number is not None:
            return number
    return None


def usable_summary(summary: Any) -> bool:
    """Whether a daily-summaries entry is real Garmin watch data.

    Garmin also returns entries from other sources (for example imported
    "fitbit" days) with nonsensical values such as negative calories.
    """
    if not isinstance(summary, Mapping) or source_of(summary) not in (None, "garmin"):
        return False
    # Days without any tracker signal are only a placeholder (basal calories), not a measured day.
    signals = (
        dig(summary, "movement", "steps", "value"),
        dig(summary, "heartRate", "restingValue"),
        summary.get("totalSteps"),
        summary.get("restingHeartRate"),
    )
    return any(x not in (None, 0) for x in signals)


def source_of(summary: Any) -> str | None:
    """The data source of a daily summary in lower case (``GARMIN`` and ``garmin`` are the same)."""
    raw = summary.get("source") if isinstance(summary, Mapping) else None
    return None if raw is None else str(raw).lower()


def from_garmin(summary: Any) -> bool:
    """Whether a single-day summary comes from Garmin (or states no source)."""
    return source_of(summary) in (None, "garmin")
