"""Services: on-demand retrieval of any Garmin endpoint, activity files, statistics backfill."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api import ENDPOINT_NAMES, GarminError, GarminRateLimitError, split_range
from .const import (
    ACTIVITY_PAGE_DEFAULT,
    ACTIVITY_SEARCH_MAX_TOTAL,
    ATTR_CONFIG_ENTRY_ID,
    DOMAIN,
    SERVICE_BACKFILL,
    SERVICE_DOWNLOAD_ACTIVITY,
    SERVICE_FETCH,
    SERVICE_SEARCH_ACTIVITIES,
)
from .coordinator import GarminConfigEntry
from .values import first_number, from_garmin, usable_summary

_LOGGER = logging.getLogger(__name__)

ATTR_ENDPOINT = "endpoint"
ATTR_DATE = "date"
ATTR_START = "start_date"
ATTR_END = "end_date"
ATTR_ACTIVITY_ID = "activity_id"
ATTR_FILTERS = "filters"
ATTR_LIMIT = "limit"
ATTR_PATH = "path"
ATTR_DAYS = "days"
ATTR_THIRD_PARTY = "include_third_party_steps"

# Longest range one call may cover (fetch and backfill), in days.
MAX_RANGE_DAYS = 3650
# The backfill works through the range in pieces of this many days and stores each piece
# right away, so a failure late in a long range keeps what was already imported.
BACKFILL_WINDOW_DAYS = 31

# Translation keys of the errors raised here (``exceptions.<key>.message`` in strings.json).
ERR_NO_ENTRY = "no_entry"
ERR_ENTRY_REQUIRED = "entry_required"
ERR_ENTRY_UNKNOWN = "entry_unknown"
ERR_ENTRY_NOT_LOADED = "entry_not_loaded"
ERR_GARMIN_FAILED = "garmin_request_failed"
ERR_INVALID_REQUEST = "invalid_request"
ERR_INVALID_DATE_RANGE = "invalid_date_range"
ERR_DATE_RANGE_TOO_LONG = "date_range_too_long"
ERR_PATH_NOT_ALLOWED = "path_not_allowed"
ERR_PATH_NOT_ZIP = "path_not_zip"
ERR_DOWNLOAD_FAILED = "download_failed"
ERR_BACKFILL_RUNNING = "backfill_running"


def _invalid(key: str, **placeholders: Any) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={k: str(v) for k, v in placeholders.items()},
    )


def _failed(key: str, **placeholders: Any) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={k: str(v) for k, v in placeholders.items()},
    )


# Activity filters that are booleans: a template may hand them over as the string "false".
_BOOL_FILTER_KEYS = ("favorite", "exclude_children", "excludeChildren", "deco_dive", "decoDive")


def _filters(value: Any) -> dict[str, Any]:
    """A mapping of activity filters; boolean filters are parsed so that ``"false"`` is false."""
    if not isinstance(value, dict):
        raise vol.Invalid("filters must be a mapping")
    result = dict(value)
    for key in _BOOL_FILTER_KEYS:
        if result.get(key) is not None:
            result[key] = cv.boolean(result[key])
    return result


BASE = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

FETCH_SCHEMA = vol.Schema(
    {
        **BASE,
        vol.Required(ATTR_ENDPOINT): vol.In(ENDPOINT_NAMES),
        vol.Optional(ATTR_DATE): cv.date,
        vol.Optional(ATTR_START): cv.date,
        vol.Optional(ATTR_END): cv.date,
        vol.Optional(ATTR_ACTIVITY_ID): cv.positive_int,
        vol.Optional(ATTR_FILTERS): _filters,
        vol.Optional(ATTR_LIMIT, default=ACTIVITY_PAGE_DEFAULT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=ACTIVITY_SEARCH_MAX_TOTAL)
        ),
    }
)

SEARCH_SCHEMA = vol.Schema(
    {
        **BASE,
        vol.Optional(ATTR_FILTERS): _filters,
        vol.Optional(ATTR_LIMIT, default=ACTIVITY_PAGE_DEFAULT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=ACTIVITY_SEARCH_MAX_TOTAL)
        ),
    }
)

DOWNLOAD_SCHEMA = vol.Schema(
    {**BASE, vol.Required(ATTR_ACTIVITY_ID): cv.positive_int, vol.Optional(ATTR_PATH): cv.string}
)

BACKFILL_SCHEMA = vol.Schema(
    {
        **BASE,
        vol.Optional(ATTR_START): cv.date,
        vol.Optional(ATTR_END): cv.date,
        vol.Optional(ATTR_DAYS, default=90): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_RANGE_DAYS)
        ),
        vol.Optional(ATTR_THIRD_PARTY, default=False): cv.boolean,
    }
)

# statistic id suffix -> (unit, candidate paths). The daily-summaries range endpoint
# is nested ("movement.steps.value"); the flat names are the single-day format.
BACKFILL_FIELDS: dict[str, tuple[str | None, tuple[tuple[str, ...], ...]]] = {
    "steps": ("steps", (("movement", "steps", "value"), ("totalSteps",))),
    "distance": ("m", (("movement", "steps", "distanceInMeters"), ("totalDistanceMeters",))),
    "active_calories": ("kcal", (("calories", "burnedActive"), ("activeKilocalories",))),
    "resting_calories": ("kcal", (("calories", "burnedResting"), ("bmrKilocalories",))),
    "total_calories": ("kcal", (("calories", "burnedTotal"), ("totalKilocalories",))),
    "resting_heart_rate": ("bpm", (("heartRate", "restingValue"), ("restingHeartRate",))),
    "min_heart_rate": ("bpm", (("heartRate", "minValue"), ("minHeartRate",))),
    "max_heart_rate": ("bpm", (("heartRate", "maxValue"), ("maxHeartRate",))),
    "stress_average": (None, (("stress", "avgLevel"), ("averageStressLevel",))),
    "stress_max": (None, (("stress", "maxLevel"), ("maxStressLevel",))),
    "body_battery_high": ("%", (("bodyBattery", "maxValue"), ("bodyBatteryHighestValue",))),
    "body_battery_low": ("%", (("bodyBattery", "minValue"), ("bodyBatteryLowestValue",))),
    "body_battery_charged": ("%", (("bodyBattery", "chargedValue"), ("bodyBatteryChargedValue",))),
    "body_battery_drained": ("%", (("bodyBattery", "drainedValue"), ("bodyBatteryDrainedValue",))),
    "moderate_intensity_minutes": ("min", (("intensityMinutes", "moderate"), ("moderateIntensityMinutes",))),
    "vigorous_intensity_minutes": ("min", (("intensityMinutes", "vigorous"), ("vigorousIntensityMinutes",))),
    "floors_ascended": (None, (("movement", "floorsAscended", "value"), ("floorsAscended",))),
    "respiration_average": ("brpm", (("respiration", "avgValue"), ("avgWakingRespirationValue",))),
}



# Days that other apps wrote into Garmin Connect (e.g. steps synced with RunGap) carry real steps,
# distance and floors, but no heart rate and only partial calories; only these fields are taken.
THIRD_PARTY_FIELDS = ("steps", "distance", "floors_ascended")

# Fields where Garmin may send 0 for "not measured" (heart rate, breathing, stress): 0 is no value
# there. Steps, floors, calories, minutes and awake counts can really be 0 and stay.
SKIP_ZERO_FIELDS = frozenset(
    {
        "resting_heart_rate",
        "min_heart_rate",
        "max_heart_rate",
        "stress_average",
        "stress_max",
        "respiration_average",
        "sleep_heart_rate",
        "sleep_stress",
        "sleep_respiration",
    }
)

# Recorder unit classes for units Home Assistant can convert (statistics cards then follow the
# unit system); other units stay without a class. Only set when the recorder knows the field.
UNIT_CLASSES: dict[str, str] = {"m": "distance", "kg": "mass", "s": "duration", "min": "duration"}


def _loaded(entry: Any) -> bool:
    return (
        getattr(entry, "state", None) is ConfigEntryState.LOADED
        and getattr(entry, "runtime_data", None) is not None
    )


def _get_entry(hass: HomeAssistant, call: ServiceCall) -> GarminConfigEntry:
    """The account a call is for.

    ``config_entry_id`` may be left out only if exactly one account exists (loaded or not):
    with several, a call must never silently fall back to whichever one happens to be loaded.
    """
    entries = list(hass.config_entries.async_entries(DOMAIN))
    wanted = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if wanted:
        entry = next((e for e in entries if e.entry_id == wanted), None)
        if entry is None:
            raise _invalid(ERR_ENTRY_UNKNOWN, entry_id=wanted)
    elif not entries:
        raise _invalid(ERR_NO_ENTRY)
    elif len(entries) == 1:
        entry = entries[0]
    else:
        raise _invalid(ERR_ENTRY_REQUIRED, entries=", ".join(f"{e.title} ({e.entry_id})" for e in entries))
    if not _loaded(entry):
        raise _invalid(ERR_ENTRY_NOT_LOADED, title=entry.title)
    return entry


def _jsonable(value: Any) -> Any:
    """Make API results safe for a service response."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _check_span(start: date, end: date) -> None:
    """Reject reversed ranges and ranges longer than ``MAX_RANGE_DAYS``."""
    if start > end:
        raise _invalid(ERR_INVALID_DATE_RANGE, start=start.isoformat(), end=end.isoformat())
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise _invalid(
            ERR_DATE_RANGE_TOO_LONG, start=start.isoformat(), end=end.isoformat(), max_days=MAX_RANGE_DAYS
        )


def _media_folder(hass: HomeAssistant) -> str:
    """Folder for downloads: HA's media folder, allowed by default and not served without login.

    (``<config>/www`` is allowed too, but everything in it is public under ``/local/``.)
    """
    media_dirs = getattr(hass.config, "media_dirs", None) or {}
    base = media_dirs.get("local") or next(iter(media_dirs.values()), None) or hass.config.path("media")
    return os.path.join(str(base), DOMAIN)


@dataclass
class ImportTally:
    """What a backfill really wrote."""

    series: set[str] = field(default_factory=set)
    rows: int = 0
    days: set[str] = field(default_factory=set)
    days_third_party: set[str] = field(default_factory=set)


def async_register_services(hass: HomeAssistant) -> None:
    """Register all services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_FETCH):
        return

    backfill_locks: dict[str, asyncio.Lock] = {}

    async def fetch(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass, call)
        data = call.data
        today = dt_util.now().date()
        if data.get(ATTR_START) or data.get(ATTR_END):
            last = data.get(ATTR_END) or data.get(ATTR_DATE) or today
            _check_span(data.get(ATTR_START) or last - timedelta(days=6), last)
        # Only the endpoint name is logged: answers can hold nutrition or cycle data.
        _LOGGER.debug("Service fetch for endpoint %s", data[ATTR_ENDPOINT])
        try:
            result = await entry.runtime_data.api.fetch(
                data[ATTR_ENDPOINT],
                day=data.get(ATTR_DATE),
                start=data.get(ATTR_START),
                end=data.get(ATTR_END),
                activity_id=data.get(ATTR_ACTIVITY_ID),
                filters=data.get(ATTR_FILTERS),
                limit=data[ATTR_LIMIT],
                today=today,
            )
        except ValueError as err:
            raise _invalid(ERR_INVALID_REQUEST, error=err) from err
        except GarminError as err:
            raise _failed(ERR_GARMIN_FAILED, error=err) from err
        return {"endpoint": data[ATTR_ENDPOINT], "data": _jsonable(result)}

    async def search_activities(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass, call)
        try:
            result = await entry.runtime_data.api.search_activities(
                limit=call.data[ATTR_LIMIT], filters=call.data.get(ATTR_FILTERS)
            )
        except ValueError as err:
            raise _invalid(ERR_INVALID_REQUEST, error=err) from err
        except GarminError as err:
            raise _failed(ERR_GARMIN_FAILED, error=err) from err
        return {"count": len(result), "activities": _jsonable(result)}

    async def download_activity(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass, call)
        activity_id = call.data[ATTR_ACTIVITY_ID]
        filename = f"activity_{activity_id}.zip"  # built from the numeric id only
        wanted = call.data.get(ATTR_PATH)
        if wanted and wanted.endswith(("/", os.sep)):
            wanted = os.path.join(wanted, filename)  # a folder: keep the safe file name
        raw = wanted or os.path.join(_media_folder(hass), filename)

        def resolve() -> tuple[str, bool]:
            # realpath resolves "..", symlinks and relative paths before the allow-list is asked
            resolved = os.path.realpath(raw)
            if os.path.isdir(resolved):
                resolved = os.path.join(resolved, filename)
            return resolved, hass.config.is_allowed_path(resolved)

        resolved, allowed = await hass.async_add_executor_job(resolve)
        if not allowed:
            raise _invalid(ERR_PATH_NOT_ALLOWED, path=resolved, folder=os.path.dirname(resolved))
        if not resolved.lower().endswith(".zip"):
            raise _invalid(ERR_PATH_NOT_ZIP, path=resolved)
        target = Path(resolved)
        try:
            payload = await entry.runtime_data.api.download_activity_zip(activity_id)
        except GarminError as err:
            raise _failed(ERR_GARMIN_FAILED, error=err) from err

        def write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            try:
                partial.write_bytes(payload)
                os.replace(partial, target)
            finally:
                partial.unlink(missing_ok=True)

        try:
            await hass.async_add_executor_job(write)
        except OSError as err:
            raise _failed(ERR_DOWNLOAD_FAILED, path=target, error=err.strerror or err) from err
        return {"path": str(target), "bytes": len(payload)}

    async def backfill(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass, call)
        today = dt_util.now().date()
        explicit_end = call.data.get(ATTR_END)
        # Today is incomplete (steps, min/max, body battery are mid-day values): only on request.
        end = min(explicit_end, today) if explicit_end else today - timedelta(days=1)
        start = call.data.get(ATTR_START) or (end - timedelta(days=call.data[ATTR_DAYS] - 1))
        _check_span(start, end)
        lock = backfill_locks.setdefault(entry.entry_id, asyncio.Lock())
        if lock.locked():
            raise _invalid(ERR_BACKFILL_RUNNING, title=entry.title)
        async with lock:
            return await _run_backfill(entry, start, end, bool(call.data.get(ATTR_THIRD_PARTY)), end >= today)

    async def _run_backfill(
        entry: GarminConfigEntry, start: date, end: date, third_party: bool, partial_day: bool
    ) -> dict[str, Any]:
        """Work through the range window by window, storing each window before asking for the next."""
        api = entry.runtime_data.api
        tally = ImportTally()
        returned: set[str] = set()
        skipped = {"days_skipped_other_source": 0, "days_skipped_placeholder": 0}
        records = {"sleep": 0, "hrv": 0, "weight": 0}
        errors: dict[str, str] = {}
        stopped: GarminError | None = None
        last_done: date | None = None
        for window_start, window_end in split_range(start, end, BACKFILL_WINDOW_DAYS):
            try:
                summaries = await api.get_daily_summaries(window_start, window_end)
            except GarminError as err:
                stopped = err
                break
            returned.update(
                str(s["calendarDate"]) for s in summaries if isinstance(s, dict) and s.get("calendarDate")
            )
            plan = _plan_days(summaries, third_party)
            skipped["days_skipped_other_source"] += plan.skipped_other_source
            skipped["days_skipped_placeholder"] += plan.skipped_placeholder
            _import_statistics(hass, entry, summaries, third_party_steps=third_party, tally=tally)
            for label, fetch_range, importer in (
                ("sleep", api.get_sleep_summaries, _import_sleep),
                ("hrv", api.get_hrv_summaries, _import_hrv),
                ("weight", api.get_weight_range, _import_weight),
            ):
                try:
                    data = await fetch_range(window_start, window_end)
                except GarminRateLimitError as err:  # asking on would only make it worse
                    stopped = err
                    break
                except GarminError as err:
                    errors.setdefault(f"{label}_error", str(err))
                    continue
                importer(hass, entry, data, tally=tally)
                if label == "weight":
                    weighings = data.get("dailyWeightSummaries") if isinstance(data, dict) else None
                    records[label] += len(weighings or [])
                else:
                    records[label] += len(data or [])
            if stopped is not None:
                break
            last_done = window_end
        if stopped is not None and last_done is None and not tally.rows:
            raise _failed(ERR_GARMIN_FAILED, error=stopped) from stopped
        result: dict[str, Any] = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "complete": stopped is None,
            "partial_day_included": partial_day,
            "days_returned": len(returned),
            "days_imported": len(tally.days),
            "days_imported_third_party_steps": len(tally.days_third_party),
            **skipped,
            "statistic_series": len(tally.series),
            "statistic_rows": tally.rows,
            **{f"{label}_records": n for label, n in records.items()},
            **errors,
        }
        if stopped is not None:
            result["error"] = str(stopped)
            result["last_completed_day"] = last_done.isoformat() if last_done else None
        return result

    hass.services.async_register(
        DOMAIN, SERVICE_FETCH, fetch, schema=FETCH_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH_ACTIVITIES,
        search_activities,
        schema=SEARCH_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_ACTIVITY,
        download_activity,
        schema=DOWNLOAD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_BACKFILL,
        backfill,
        schema=BACKFILL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


SLEEP_FIELDS: dict[str, tuple[str | None, tuple[tuple[str, ...], ...]]] = {
    "sleep_duration": ("s", (("sleepTimeSeconds",),)),
    "sleep_deep": ("s", (("deepSleepSeconds",),)),
    "sleep_light": ("s", (("lightSleepSeconds",),)),
    "sleep_rem": ("s", (("remSleepSeconds",),)),
    "sleep_awake": ("s", (("awakeSleepSeconds",),)),
    "sleep_score": (None, (("sleepScores", "overall", "value"),)),
    "sleep_heart_rate": ("bpm", (("avgHeartRate",),)),
    "sleep_stress": (None, (("avgSleepStress",),)),
    "sleep_respiration": ("brpm", (("averageRespirationValue",),)),
    "sleep_need": ("min", (("sleepNeed", "actual"),)),
    "sleep_awake_count": (None, (("awakeCount",),)),
}
HRV_FIELDS: dict[str, tuple[str | None, tuple[tuple[str, ...], ...]]] = {
    "hrv_last_night": ("ms", (("lastNightAvg",),)),
    "hrv_weekly_average": ("ms", (("weeklyAvg",),)),
    "hrv_5_min_high": ("ms", (("lastNight5MinHigh",),)),
}
# name -> (unit, paths, divisor): Garmin reports weights in grams
WEIGHT_FIELDS: dict[str, tuple[str | None, tuple[tuple[str, ...], ...], float]] = {
    "weight": ("kg", (("weight",),), 1000.0),
    "bmi": (None, (("bmi",),), 1.0),
    "body_fat": ("%", (("bodyFat",),), 1.0),
    "body_water": ("%", (("bodyWater",),), 1.0),
    "muscle_mass": ("kg", (("muscleMass",),), 1000.0),
    "bone_mass": ("kg", (("boneMass",),), 1000.0),
}



# Entries Garmin creates itself when the profile weight is edited are not weighings.
NOT_A_WEIGHING = ("USER_SETTING", "CHANGE_LOG")


def _third_party_day(summary: Any) -> bool:
    """A day from another source that still has a usable step count."""
    if not isinstance(summary, dict) or from_garmin(summary):
        return False
    steps = first_number(summary, *BACKFILL_FIELDS["steps"][1])
    return steps is not None and steps > 0


def _local_day(day: Any) -> datetime | None:
    try:
        return dt_util.start_of_local_day(date.fromisoformat(str(day)))
    except ValueError:
        return None


@dataclass
class DayPlan:
    """Which entry stands for each day, and what was left out."""

    chosen: list[tuple[str, dict[str, Any], bool]] = field(default_factory=list)  # day, summary, third party?
    skipped_other_source: int = 0
    skipped_placeholder: int = 0


def _plan_days(summaries: list[Any], third_party_steps: bool) -> DayPlan:
    """One entry per ``calendarDate``: Garmin (or source-less) data first, other sources only as a fallback.

    A day is taken from another source only if it has no usable Garmin entry, the opt-in is on and
    that entry has steps. Entries without a valid date are ignored; among equals the first one wins.
    """
    by_day: dict[str, list[dict[str, Any]]] = {}
    for summary in summaries:
        day = summary.get("calendarDate") if isinstance(summary, dict) else None
        if day and _local_day(day) is not None:
            by_day.setdefault(str(day), []).append(summary)
    plan = DayPlan()
    for day in sorted(by_day):
        entries = by_day[day]
        garmin = [e for e in entries if from_garmin(e)]
        usable = next((e for e in garmin if usable_summary(e)), None)
        if usable is not None:
            plan.chosen.append((day, usable, False))
            continue
        other = next((e for e in entries if _third_party_day(e)), None) if third_party_steps else None
        if other is not None:
            plan.chosen.append((day, other, True))
        elif garmin:
            plan.skipped_placeholder += 1
        else:
            plan.skipped_other_source += 1
    return plan


def _import_statistics(
    hass: HomeAssistant,
    entry: GarminConfigEntry,
    summaries: list[Any],
    *,
    third_party_steps: bool = False,
    tally: ImportTally | None = None,
) -> int:
    """Write one value per day into external long-term statistics; returns the number of series written.

    Each statistic id is ``garmin_personal:<entry_id>_<name>``; the value Garmin
    reports for a day is stored as that day's (hourly, at local midnight) mean.
    Re-running the service overwrites the same hours, so it is safe to repeat.
    """
    from homeassistant.components.recorder.models import StatisticData

    tally = tally if tally is not None else ImportTally()
    plan = _plan_days(summaries, third_party_steps)
    count = 0
    for name, (unit, paths) in BACKFILL_FIELDS.items():
        rows: list[StatisticData] = []
        days: list[tuple[str, bool]] = []
        for day, summary, is_third_party in plan.chosen:
            if is_third_party and name not in THIRD_PARTY_FIELDS:
                continue
            value = first_number(summary, *paths)
            if value is None or value < 0 or (value == 0 and name in SKIP_ZERO_FIELDS):
                continue
            rows.append(
                StatisticData(start=_local_day(day), mean=float(value), min=float(value), max=float(value))
            )
            days.append((day, is_third_party))
        if _write_series(hass, entry, name, unit, rows, tally=tally):
            count += 1
            for day, is_third_party in days:
                (tally.days_third_party if is_third_party else tally.days).add(day)
    return count


def _write_series(
    hass: HomeAssistant,
    entry: GarminConfigEntry,
    name: str,
    unit: str | None,
    rows: list[Any],
    *,
    tally: ImportTally | None = None,
) -> bool:
    """Store one series of daily values as an external statistic; False if there is nothing to store."""
    if not rows:
        return False
    from homeassistant.components.recorder.models import StatisticMetaData
    from homeassistant.components.recorder.statistics import async_add_external_statistics

    try:
        from homeassistant.components.recorder.models import StatisticMeanType
    except ImportError:  # older Home Assistant
        StatisticMeanType = None  # noqa: N806

    # Statistic ids and names stay as first released (they differ from the live sensors' keys in
    # places, e.g. ``sleep_respiration``): renaming would orphan the history already stored.
    metadata: dict[str, Any] = {
        "has_sum": False,
        "name": f"{entry.title} {name.replace('_', ' ')}",
        "source": DOMAIN,
        "statistic_id": f"{DOMAIN}:{entry.entry_id.lower()}_{name}",
        "unit_of_measurement": unit,
    }
    if StatisticMeanType is not None:
        metadata["mean_type"] = StatisticMeanType.ARITHMETIC
    else:
        metadata["has_mean"] = True
    if "unit_class" in getattr(StatisticMetaData, "__annotations__", {}):
        metadata["unit_class"] = UNIT_CLASSES.get(unit or "")
    async_add_external_statistics(hass, StatisticMetaData(**metadata), rows)
    if tally is not None:
        tally.series.add(name)
        tally.rows += len(rows)
    return True


def _day_rows(
    records: list[Any],
    paths: tuple[tuple[str, ...], ...],
    *,
    day_key: str,
    accept: Any = None,
    scale: float = 1.0,
    skip_zero: bool = False,
) -> list[Any]:
    """One statistic row per day: the number found at ``paths``, taken at local midnight of the day.

    A day that appears twice keeps its first entry (never two rows for the same hour).
    """
    from homeassistant.components.recorder.models import StatisticData

    rows = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or (accept is not None and not accept(record)):
            continue
        value = first_number(record, *paths)
        day = record.get(day_key)
        if value is None or value < 0 or (skip_zero and value == 0) or not day or str(day) in seen:
            continue
        start = _local_day(day)
        if start is None:
            continue
        seen.add(str(day))
        value = float(value) / scale
        rows.append(StatisticData(start=start, mean=value, min=value, max=value))
    return rows


def _import_sleep(
    hass: HomeAssistant, entry: GarminConfigEntry, sleeps: list[Any], *, tally: ImportTally | None = None
) -> int:
    """Sleep per night (dated by the wake-up day Garmin uses): only nights with measured sleep."""
    accept = lambda s: (first_number(s, ("sleepTimeSeconds",)) or 0) > 0  # noqa: E731
    count = 0
    for name, (unit, paths) in SLEEP_FIELDS.items():
        rows = _day_rows(sleeps, paths, day_key="calendarDate", accept=accept, skip_zero=name in SKIP_ZERO_FIELDS)
        count += _write_series(hass, entry, name, unit, rows, tally=tally)
    return count


def _import_hrv(
    hass: HomeAssistant, entry: GarminConfigEntry, summaries: list[Any], *, tally: ImportTally | None = None
) -> int:
    count = 0
    for name, (unit, paths) in HRV_FIELDS.items():
        rows = _day_rows(summaries, paths, day_key="calendarDate", skip_zero=True)
        count += _write_series(hass, entry, name, unit, rows, tally=tally)
    return count


def _import_weight(
    hass: HomeAssistant, entry: GarminConfigEntry, weights: Any, *, tally: ImportTally | None = None
) -> int:
    """Weighings (manual entries or a scale), one value per day; body composition only where Garmin has it."""
    days = (weights or {}).get("dailyWeightSummaries") if isinstance(weights, dict) else None
    records = []
    for item in days or []:
        latest = item.get("latestWeight") if isinstance(item, dict) else None
        if isinstance(latest, dict) and str(latest.get("sourceType", "")).upper() not in NOT_A_WEIGHING:
            records.append({**latest, "calendarDate": latest.get("calendarDate") or item.get("summaryDate")})
    count = 0
    for name, (unit, paths, scale) in WEIGHT_FIELDS.items():
        rows = _day_rows(records, paths, day_key="calendarDate", scale=scale, skip_zero=True)
        count += _write_series(hass, entry, name, unit, rows, tally=tally)
    return count
