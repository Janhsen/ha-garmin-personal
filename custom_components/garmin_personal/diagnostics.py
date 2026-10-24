"""Diagnostics download (no key, no health values)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import GarminConfigEntry
from .repairs import key_expires_at


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GarminConfigEntry
) -> dict[str, Any]:
    """Structure and health of the data, not its content."""
    groups: dict[str, Any] = {}
    for name, coordinator in entry.runtime_data.coordinators.items():
        data = coordinator.data or {}
        groups[name] = {
            "last_update_success": coordinator.last_update_success,
            "interval": str(coordinator.update_interval),
            "endpoints_with_data": sorted(k for k, v in data.items() if v not in (None, [], {}) and not k.startswith("_")),
            "endpoints_empty": sorted(k for k, v in data.items() if v in (None, [], {}) and not k.startswith("_")),
        }
    expires = key_expires_at(entry)
    return {
        "entry": async_redact_data(dict(entry.data), {"api_key"}),
        "key_expires_at": expires.isoformat() if expires else None,
        "options": dict(entry.options),
        "groups": groups,
    }
