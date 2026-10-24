"""Services: on-demand retrieval of any Garmin endpoint, activity files, statistics backfill."""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api import ENDPOINT_NAMES, GarminError
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

BASE = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

FETCH_SCHEMA = vol.Schema(
    {
        **BASE,
        vol.Required(ATTR_ENDPOINT): vol.In(ENDPOINT_NAMES),
        vol.Optional(ATTR_DATE): cv.date,
        vol.Optional(ATTR_START): cv.date,
        vol.Optional(ATTR_END): cv.date,
        vol.Optional(ATTR_ACTIVITY_ID): cv.positive_int,
        vol.Optional(ATTR_FILTERS): dict,
        vol.Optional(ATTR_LIMIT, default=ACTIVITY_PAGE_DEFAULT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=ACTIVITY_SEARCH_MAX_TOTAL)
        ),
    }
)

SEARCH_SCHEMA = vol.Schema(
    {
        **BASE,
        vol.Optional(ATTR_FILTERS): dict,
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
        vol.Optional(ATTR_DAYS, default=90): vol.All(vol.Coerce(int), vol.Range(min=1, max=3650)),
    }
)

# statistic id suffix -> (daily summary field, unit)
BACKFILL_FIELDS: dict[str, tuple[str, str | None]] = {
    "steps": ("totalSteps", "steps"),
    "distance": ("totalDistanceMeters", "m"),
    "active_calories": ("activeKilocalories", "kcal"),
    "total_calories": ("totalKilocalories", "kcal"),
    "resting_heart_rate": ("restingHeartRate", "bpm"),
    "min_heart_rate": ("minHeartRate", "bpm"),
    "max_heart_rate": ("maxHeartRate", "bpm"),
    "stress_average": ("averageStressLevel", None),
    "body_battery_high": ("bodyBatteryHighestValue", "%"),
    "body_battery_low": ("bodyBatteryLowestValue", "%"),
    "moderate_intensity_minutes": ("moderateIntensityMinutes", "min"),
    "vigorous_intensity_minutes": ("vigorousIntensityMinutes", "min"),
    "floors_ascended": ("floorsAscended", None),
}


def _get_entry(hass: HomeAssistant, call: ServiceCall) -> GarminConfigEntry:
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]
    wanted = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if wanted:
        for entry in entries:
            if entry.entry_id == wanted:
                return entry
        raise ServiceValidationError(f"Unknown or not loaded Garmin account: {wanted}")
    if len(entries) == 1:
        return entries[0]
    if not entries:
        raise ServiceValidationError("No Garmin account is set up")
    raise ServiceValidationError("Several Garmin accounts exist: pass config_entry_id")


def _jsonable(value: Any) -> Any:
    """Make API results safe for a service response."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def async_register_services(hass: HomeAssistant) -> None:
    """Register all services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_FETCH):
        return

    async def fetch(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass, call)
        data = call.data
        try:
            result = await entry.runtime_data.api.fetch(
                data[ATTR_ENDPOINT],
                day=data.get(ATTR_DATE),
                start=data.get(ATTR_START),
                end=data.get(ATTR_END),
                activity_id=data.get(ATTR_ACTIVITY_ID),
                filters=data.get(ATTR_FILTERS),
                limit=data[ATTR_LIMIT],
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        except GarminError as err:
            raise HomeAssistantError(f"Garmin request failed: {err}") from err
        return {"endpoint": data[ATTR_ENDPOINT], "data": _jsonable(result)}

    async def search_activities(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass, call)
        try:
            result = await entry.runtime_data.api.search_activities(
                limit=call.data[ATTR_LIMIT], filters=call.data.get(ATTR_FILTERS)
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        except GarminError as err:
            raise HomeAssistantError(f"Garmin request failed: {err}") from err
        return {"count": len(result), "activities": _jsonable(result)}

    async def download_activity(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass, call)
        activity_id = call.data[ATTR_ACTIVITY_ID]
        target = Path(
            call.data.get(ATTR_PATH)
            or hass.config.path(DOMAIN, f"activity_{activity_id}.zip")
        )
        if not hass.config.is_allowed_path(str(target)):
            raise ServiceValidationError(
                f"{target} is not in an allowed folder (allowlist_external_dirs)"
            )
        try:
            payload = await entry.runtime_data.api.download_activity_zip(activity_id)
        except GarminError as err:
            raise HomeAssistantError(f"Garmin request failed: {err}") from err

        def write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

        await hass.async_add_executor_job(write)
        return {"path": str(target), "bytes": len(payload)}

    async def backfill(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry(hass, call)
        end = call.data.get(ATTR_END) or dt_util.now().date()
        start = call.data.get(ATTR_START) or end.fromordinal(end.toordinal() - call.data[ATTR_DAYS] + 1)
        if start > end:
            raise ServiceValidationError("start_date is after end_date")
        try:
            summaries = await entry.runtime_data.api.get_daily_summaries(start, end)
        except GarminError as err:
            raise HomeAssistantError(f"Garmin request failed: {err}") from err
        imported = _import_statistics(hass, entry, summaries)
        return {"days": len({s.get("calendarDate") for s in summaries if isinstance(s, dict)}),
                "statistics": imported}

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


def _import_statistics(hass: HomeAssistant, entry: GarminConfigEntry, summaries: list[Any]) -> int:
    """Write one value per day into external long-term statistics.

    Each statistic id is ``garmin_personal:<entry_id>_<name>``; the value Garmin
    reports for a day is stored as that day's (hourly, at local midnight) mean.
    Re-running the service overwrites the same hours, so it is safe to repeat.
    """
    from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
    from homeassistant.components.recorder.statistics import async_add_external_statistics

    try:
        from homeassistant.components.recorder.models import StatisticMeanType
    except ImportError:  # older Home Assistant
        StatisticMeanType = None  # noqa: N806

    count = 0
    for name, (field, unit) in BACKFILL_FIELDS.items():
        rows: list[StatisticData] = []
        for summary in summaries:
            if not isinstance(summary, dict):
                continue
            value = summary.get(field)
            day = summary.get("calendarDate")
            if isinstance(value, bool) or not isinstance(value, int | float) or not day:
                continue
            try:
                start = dt_util.start_of_local_day(date.fromisoformat(str(day)))
            except ValueError:
                continue
            rows.append(StatisticData(start=start, mean=float(value), min=float(value), max=float(value)))
        if not rows:
            continue
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
            metadata["unit_class"] = None
        async_add_external_statistics(hass, StatisticMetaData(**metadata), rows)
        count += 1
    return count
