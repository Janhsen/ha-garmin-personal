"""Shared entity helpers."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN
from .coordinator import GarminConfigEntry


def device_info(entry: GarminConfigEntry) -> DeviceInfo:
    """One service device per Garmin account."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Garmin",
        model="Garmin Connect Personal API",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://connect.garmin.com",
    )
