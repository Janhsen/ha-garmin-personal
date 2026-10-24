"""Writing external long-term statistics (shared by the services and the coordinator)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .intraday import HourStat

# Recorder unit classes for units Home Assistant can convert (statistics cards then follow the
# unit system); other units stay without a class. Only set when the recorder knows the field.
UNIT_CLASSES: dict[str, str] = {"m": "distance", "kg": "mass", "s": "duration", "min": "duration"}


def statistic_id(entry_id: str, name: str) -> str:
    """``garmin_personal:<entry_id lower>_<name>``."""
    return f"{DOMAIN}:{entry_id.lower()}_{name}"


def display_name(title: str, name: str) -> str:
    """``Alex`` + ``heart_rate_hourly`` -> ``Alex heart rate (hourly)``; only the name changes, never the id."""
    words = name.replace("_", " ")
    if words.endswith(" hourly"):
        words = f"{words[: -len(' hourly')]} (hourly)"
    return f"{title} {words}"


def build_metadata(entry_id: str, title: str, name: str, unit: str | None) -> Any:
    """Metadata of an external statistic with mean (no sum), for the installed Home Assistant."""
    from homeassistant.components.recorder.models import StatisticMetaData

    try:
        from homeassistant.components.recorder.models import StatisticMeanType
    except ImportError:  # older Home Assistant
        StatisticMeanType = None  # noqa: N806

    # Statistic ids and names stay as first released (they differ from the live sensors' keys in
    # places, e.g. ``sleep_respiration``): renaming would orphan the history already stored.
    metadata: dict[str, Any] = {
        "has_sum": False,
        "name": display_name(title, name),
        "source": DOMAIN,
        "statistic_id": statistic_id(entry_id, name),
        "unit_of_measurement": unit,
    }
    if StatisticMeanType is not None:
        metadata["mean_type"] = StatisticMeanType.ARITHMETIC
    else:
        metadata["has_mean"] = True
    if "unit_class" in getattr(StatisticMetaData, "__annotations__", {}):
        metadata["unit_class"] = UNIT_CLASSES.get(unit or "")
    return StatisticMetaData(**metadata)


def write_hourly(
    hass: HomeAssistant,
    entry_id: str,
    title: str,
    name: str,
    unit: str | None,
    hours: Mapping[datetime, HourStat],
) -> int:
    """Store one row per full hour (min, max, mean); returns the number of rows.

    The same statistic id and hour overwrite each other, so later corrections by Garmin replace
    the earlier values. Rows are written in time order.
    """
    if not hours:
        return 0
    from homeassistant.components.recorder.models import StatisticData
    from homeassistant.components.recorder.statistics import async_add_external_statistics

    rows = [
        StatisticData(start=start, mean=stat.mean, min=stat.minimum, max=stat.maximum)
        for start, stat in sorted(hours.items())
    ]
    async_add_external_statistics(hass, build_metadata(entry_id, title, name, unit), rows)
    return len(rows)
