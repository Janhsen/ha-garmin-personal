"""Diagnostics download.

Contains no API key, no Garmin account id, no measured values, no coordinates and no
activity names: only which endpoints answered, timings, options and entity counts.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_API_KEY, CONF_KEY_VALIDITY
from .coordinator import GarminConfigEntry
from .repairs import key_expires_at

# Redacted although the entry data does not normally hold them (defence in depth).
TO_REDACT = {CONF_API_KEY, "api_key", "unique_id", "title", "userProfileId", "displayName"}


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _group(coordinator: Any) -> dict[str, Any]:
    data = coordinator.data or {}
    names = [k for k in data if not str(k).startswith("_")]
    error = getattr(coordinator, "last_exception", None)
    return {
        "last_update_success": coordinator.last_update_success,
        "last_exception": type(error).__name__ if error is not None else None,
        "last_update_success_time": _iso(getattr(coordinator, "last_update_success_time", None)),
        "interval": str(coordinator.update_interval),
        "data_day": data.get("_day"),
        "endpoints_with_data": sorted(k for k in names if data[k] not in (None, [], {})),
        "endpoints_empty": sorted(k for k in names if data[k] in (None, [], {})),
    }


def _entities(hass: HomeAssistant, entry: GarminConfigEntry) -> dict[str, Any]:
    """Counts per platform and the keys of disabled entities (keys only, no states)."""
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    platforms: dict[str, dict[str, Any]] = {}
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        info = platforms.setdefault(
            item.domain,
            {"total": 0, "disabled_by_integration": [], "disabled_by_user": [], "other_disabled": 0},
        )
        info["total"] += 1
        disabler = getattr(item.disabled_by, "value", item.disabled_by)
        key = str(item.unique_id).removeprefix(prefix)
        if disabler == "integration":
            info["disabled_by_integration"].append(key)
        elif disabler == "user":
            info["disabled_by_user"].append(key)
        elif disabler is not None:
            info["other_disabled"] += 1
    for info in platforms.values():
        info["disabled_by_integration"].sort()
        info["disabled_by_user"].sort()
    return {
        "total": sum(p["total"] for p in platforms.values()),
        "enabled": sum(
            p["total"] - len(p["disabled_by_integration"]) - len(p["disabled_by_user"]) - p["other_disabled"]
            for p in platforms.values()
        ),
        "by_platform": platforms,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GarminConfigEntry
) -> dict[str, Any]:
    """Structure and health of the data, not its content."""
    expires = key_expires_at(entry)
    return {
        "entry": {
            "version": f"{entry.version}.{entry.minor_version}",
            "state": str(getattr(entry.state, "value", entry.state)),
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
            "unique_id": "**REDACTED**" if entry.unique_id else None,
        },
        "key": {
            "expires_at": expires.isoformat() if expires else None,
            "expiry_source": "calculated from the validity the user entered (Garmin does not report it)",
            "validity_days": entry.data.get(CONF_KEY_VALIDITY),
        },
        "groups": {name: _group(c) for name, c in entry.runtime_data.coordinators.items()},
        "entities": _entities(hass, entry),
    }
