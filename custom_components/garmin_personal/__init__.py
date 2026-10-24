"""Garmin Connect Personal API integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import GarminPersonalApi
from .const import (
    CONF_API_KEY,
    CONF_PRUNED,
    DEFAULT_ACTIVITY_INTERVAL,
    DEFAULT_BODY_INTERVAL,
    DEFAULT_DAILY_INTERVAL,
    DEFAULT_PROFILE_INTERVAL,
    DEFAULT_SLEEP_INTERVAL,
    DOMAIN,
    OPT_DAILY_INTERVAL,
    OPT_INTRADAY,
)
from .coordinator import (
    GarminActivityCoordinator,
    GarminConfigEntry,
    GarminCoordinator,
    GarminDailyCoordinator,
    GarminProfileCoordinator,
    GarminRuntimeData,
    activity_calls,
    body_calls,
    make_daily_calls,
    profile_calls,
    sleep_calls,
)
from .repairs import update_key_expiry_issue
from .sensor import sensors_to_prune
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once for the whole integration."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GarminConfigEntry) -> bool:
    """Set up one Garmin account."""
    api = GarminPersonalApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    runtime = GarminRuntimeData(api=api)

    daily_minutes = entry.options.get(OPT_DAILY_INTERVAL, DEFAULT_DAILY_INTERVAL)
    runtime.coordinators = {
        "daily": GarminDailyCoordinator(
            hass, entry, api, "daily", timedelta(minutes=daily_minutes),
            make_daily_calls(bool(entry.options.get(OPT_INTRADAY, False))),
        ),
        "sleep": GarminCoordinator(
            hass,
            entry,
            api,
            "sleep",
            timedelta(minutes=DEFAULT_SLEEP_INTERVAL),
            sleep_calls,
            sticky=("sleep", "hrv_summaries"),
        ),
        "body": GarminCoordinator(
            hass,
            entry,
            api,
            "body",
            timedelta(minutes=DEFAULT_BODY_INTERVAL),
            body_calls,
            sticky=("weight", "fitness_age"),
        ),
        "activities": GarminActivityCoordinator(
            hass,
            entry,
            api,
            "activities",
            timedelta(minutes=DEFAULT_ACTIVITY_INTERVAL),
            activity_calls,
            sticky=("activities",),
        ),
        "profile": GarminProfileCoordinator(
            hass,
            entry,
            api,
            "profile",
            timedelta(minutes=DEFAULT_PROFILE_INTERVAL),
            profile_calls,
            sticky=("profile", "hr_zones"),
        ),
    }
    daily = runtime.coordinators["daily"]
    assert isinstance(daily, GarminDailyCoordinator)  # noqa: S101
    daily.followers = [runtime.coordinators[n] for n in ("sleep", "body", "activities")]
    entry.runtime_data = runtime

    # The daily group decides whether setup works at all (bad key -> reauth,
    # network trouble -> retry). The others fill in on their own; a broken
    # optional endpoint must not stop the integration from loading.
    await runtime.coordinators["daily"].async_config_entry_first_refresh()
    for name, coordinator in runtime.coordinators.items():
        if name != "daily":
            await coordinator.async_refresh()

    update_key_expiry_issue(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _disable_empty_sensors_once(hass, entry)
    runtime.options = dict(entry.options)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options))
    return True


def _disable_empty_sensors_once(hass: HomeAssistant, entry: GarminConfigEntry) -> None:
    """On the first complete refresh, disable sensors Garmin has no value for.

    Runs once per account. Only sensors whose endpoint answered but whose field is
    empty are disabled, and only if they were still enabled; they can be enabled
    again at any time.
    """
    if entry.data.get(CONF_PRUNED):
        return
    coordinators = entry.runtime_data.coordinators
    if not all(c.last_update_success and c.data for c in coordinators.values()):
        return  # try again at the next start, with complete data
    registry = er.async_get(hass)
    for key in sensors_to_prune({name: c.data for name, c in coordinators.items()}):
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
        registered = registry.async_get(entity_id) if entity_id else None
        if registered is not None and registered.disabled_by is None:
            registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_PRUNED: True})


async def _async_reload_on_options(hass: HomeAssistant, entry: GarminConfigEntry) -> None:
    # Reauth/reconfigure reload the entry themselves; only react to option changes.
    if dict(entry.options) != entry.runtime_data.options:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: GarminConfigEntry) -> bool:
    """Unload the platforms."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
