"""Pure helpers to pick values out of Garmin's JSON (no Home Assistant imports)."""

from __future__ import annotations

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
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def number_at(*path: str | int, scale: float | None = None, digits: int | None = None) -> ValueFn:
    """Value function: a number at ``path``, optionally divided by ``scale``."""

    def value(data: Mapping[str, Any]) -> float | int | None:
        number = to_number(dig(data, *path))
        if number is None:
            return None
        if scale:
            number = number / scale
        if digits is not None:
            number = round(number, digits)
        return number

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


def latest_weight(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The newest weigh-in (``DateWeight``) from a ``weight_range`` response."""
    summaries = dig(data, "weight", "dailyWeightSummaries")
    if not isinstance(summaries, list):
        return None
    candidates = [
        item
        for item in summaries
        if isinstance(item, Mapping) and isinstance(item.get("latestWeight"), Mapping)
    ]
    if not candidates:
        return None
    newest = max(candidates, key=lambda item: str(item.get("summaryDate") or ""))
    return newest["latestWeight"]


def weight_at(key: str, *, scale: float | None = None, digits: int | None = None) -> ValueFn:
    """Value function: one field of the newest weigh-in."""

    def value(data: Mapping[str, Any]) -> float | int | None:
        entry = latest_weight(data)
        number = to_number(entry.get(key)) if entry else None
        if number is None:
            return None
        if scale:
            number = number / scale
        if digits is not None:
            number = round(number, digits)
        return number

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
        return to_number(zones.get(key)) if zones else None

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


def item_number(group: str, key: str, *, scale: float | None = None, digits: int | None = None) -> ValueFn:
    """Value function: a number from the last element of ``data[group]``."""

    def value(data: Mapping[str, Any]) -> float | int | None:
        item = last_item(data, group)
        number = to_number(item.get(key)) if item else None
        if number is None:
            return None
        if scale:
            number = number / scale
        if digits is not None:
            number = round(number, digits)
        return number

    return value


def activity_number(
    *path: str | int, scale: float | None = None, digits: int | None = None
) -> ValueFn:
    """Value function: a number from the newest activity."""

    def value(data: Mapping[str, Any]) -> float | int | None:
        activity = first_item(data, "activities")
        number = to_number(dig(activity, *path)) if activity else None
        if number is None:
            return None
        if scale:
            number = number / scale
        if digits is not None:
            number = round(number, digits)
        return number

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
