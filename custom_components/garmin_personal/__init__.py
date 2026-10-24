"""Garmin Connect Personal API integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .api import GarminAuthError, GarminPersonalApi
from .const import (
    ACCOUNT_ID_LEGACY,
    ACCOUNT_ID_PROFILE,
    CONF_ACCOUNT_ID_SOURCE,
    CONF_API_KEY,
    CONF_PRUNED,
    DEFAULT_ACTIVITY_INTERVAL,
    DEFAULT_BODY_INTERVAL,
    DEFAULT_DAILY_INTERVAL,
    DEFAULT_PROFILE_INTERVAL,
    DEFAULT_SLEEP_INTERVAL,
    DOMAIN,
    ENTRY_MINOR_VERSION,
    ENTRY_VERSION,
    KEY_EXPIRY_CHECK_INTERVAL,
    OPT_DAILY_INTERVAL,
    OPT_HISTORY_AUTO,
    OPT_HOURLY_STATS,
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
from .repairs import remove_key_expiry_issue, update_key_expiry_issue
from .sensor import prune_blocker, sensors_to_prune
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

# A secondary group whose first refresh failed is asked again after this time, at most this often.
SETUP_RETRY_DELAY = timedelta(minutes=5)
SETUP_RETRY_ATTEMPTS = 3

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.EVENT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once for the whole integration."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GarminConfigEntry) -> bool:
    """Set up one Garmin account."""
    try:
        api = GarminPersonalApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    except (GarminAuthError, KeyError) as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err
    runtime = GarminRuntimeData(api=api)

    daily_minutes = entry.options.get(OPT_DAILY_INTERVAL, DEFAULT_DAILY_INTERVAL)
    runtime.coordinators = {
        "daily": GarminDailyCoordinator(
            hass, entry, api, "daily", timedelta(minutes=daily_minutes),
            make_daily_calls(bool(entry.options.get(OPT_INTRADAY, False))),
            hourly_stats=bool(entry.options.get(OPT_HOURLY_STATS, True)),
            history_auto=bool(entry.options.get(OPT_HISTORY_AUTO, True)),
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

    _adopt_profile_id(hass, entry)
    _watch_key_expiry(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _disable_empty_sensors_once(hass, entry)
    _retry_failed_groups(hass, entry)
    # No update listener: option changes reload through OptionsFlowWithReload,
    # reauth/reconfigure through async_update_reload_and_abort.
    return True


@callback
def _retry_failed_groups(hass: HomeAssistant, entry: GarminConfigEntry, attempt: int = 1) -> None:
    """Ask the secondary groups whose first refresh failed again soon, instead of at their normal interval.

    Without this a hiccup at the start would leave the profile sensors (24 h interval) or the sleep sensors
    (2 h) unavailable until the next regular poll. The daily group has its own retry through setup.
    """
    failed = [c for name, c in entry.runtime_data.coordinators.items() if name != "daily" and not c.last_update_success]
    if not failed or attempt > SETUP_RETRY_ATTEMPTS:
        return

    async def _retry(_now: Any) -> None:
        for coordinator in failed:
            await coordinator.async_refresh()
        _retry_failed_groups(hass, entry, attempt + 1)

    entry.async_on_unload(async_call_later(hass, SETUP_RETRY_DELAY.total_seconds(), _retry))


@callback
def _watch_key_expiry(hass: HomeAssistant, entry: GarminConfigEntry) -> None:
    """Check the (calculated) key expiry now and then hourly, independent of any polling."""
    update_key_expiry_issue(hass, entry)

    @callback
    def _check(_now: Any) -> None:
        update_key_expiry_issue(hass, entry)

    entry.async_on_unload(async_track_time_interval(hass, _check, KEY_EXPIRY_CHECK_INTERVAL))


def _adopt_profile_id(hass: HomeAssistant, entry: GarminConfigEntry) -> None:
    """Move an entry that still uses the old display-name unique_id to Garmin's userProfileId.

    Runs after the first successful refresh (the daily summary carries the id), so the
    migration needs no extra request. Entities and devices are keyed by the entry id, so
    nothing else changes. If another entry already has that id, nothing is changed.
    """
    if entry.data.get(CONF_ACCOUNT_ID_SOURCE, ACCOUNT_ID_LEGACY) == ACCOUNT_ID_PROFILE:
        return
    summary = (entry.runtime_data.coordinators["daily"].data or {}).get("summary")
    raw = summary.get("userProfileId") if isinstance(summary, Mapping) else None
    if raw in (None, ""):
        return  # try again at the next start
    profile_id = str(raw)
    if any(
        other.entry_id != entry.entry_id and other.unique_id == profile_id
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        _LOGGER.warning("Another Garmin entry already uses this account; entry not migrated")
        return
    hass.config_entries.async_update_entry(
        entry,
        unique_id=profile_id,
        data={**entry.data, CONF_ACCOUNT_ID_SOURCE: ACCOUNT_ID_PROFILE},
    )
    _LOGGER.info("Garmin entry %s now identifies its account by the Garmin profile id", entry.title)


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
    data_by_group = {name: c.data for name, c in coordinators.items()}
    created = getattr(entry, "created_at", None)
    reason = prune_blocker(data_by_group, created)
    if reason is not None:
        # Too early to decide: not done, so the next start tries again.
        _LOGGER.debug("Not disabling empty sensors yet: %s", reason)
        return
    registry = er.async_get(hass)
    disabled: list[str] = []
    for key in sensors_to_prune(data_by_group, created):
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
        registered = registry.async_get(entity_id) if entity_id else None
        if registered is not None and registered.disabled_by is None:
            registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
            disabled.append(key)
    if disabled:
        _LOGGER.info(
            "Disabled %d sensors Garmin has no value for (enable them again in the entity "
            "registry if needed): %s", len(disabled), ", ".join(sorted(disabled)),
        )
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_PRUNED: True})


async def async_migrate_entry(hass: HomeAssistant, entry: GarminConfigEntry) -> bool:
    """Bring older entries up to the current version without any network access.

    1.1 -> 1.2: the unique_id was a display name (or name slug). Mark such entries as
    ``legacy``; ``_adopt_profile_id`` moves them to Garmin's profile id on the next
    successful setup, and reauth/reconfigure do the same.
    """
    if entry.version > ENTRY_VERSION:
        return False  # created by a newer version of the integration
    if entry.minor_version < 2:
        data = dict(entry.data)
        data.setdefault(CONF_ACCOUNT_ID_SOURCE, ACCOUNT_ID_LEGACY)
        hass.config_entries.async_update_entry(
            entry, data=data, version=ENTRY_VERSION, minor_version=ENTRY_MINOR_VERSION
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GarminConfigEntry) -> bool:
    """Unload the platforms and stop the background jobs; the expiry timer is released by the entry.

    The jobs (hourly statistics, history filling) are stopped and awaited, so that none of them keeps
    writing with the old state while the entry is set up again; a write that is interrupted notes what
    it already handed over in the ledger.
    """
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await _stop_background_jobs(entry)
    return unloaded


async def _stop_background_jobs(entry: GarminConfigEntry) -> None:
    runtime = getattr(entry, "runtime_data", None)
    daily = (getattr(runtime, "coordinators", None) or {}).get("daily")
    stop_jobs = getattr(daily, "async_stop_jobs", None)
    if stop_jobs is not None:
        await stop_jobs()
    manager = getattr(runtime, "history", None)
    if manager is not None:
        await manager.async_stop()


async def async_remove_entry(hass: HomeAssistant, entry: GarminConfigEntry) -> None:
    """Clean up what lives outside the entry. Imported statistics are kept on purpose."""
    remove_key_expiry_issue(hass, entry)
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.activities").async_remove()
    _LOGGER.info(
        "Garmin entry removed. Statistics imported with backfill_statistics stay in the "
        "database; delete them in Developer tools > Statistics if you no longer want them."
    )
