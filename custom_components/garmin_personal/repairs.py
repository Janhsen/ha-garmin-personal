"""Repair issue that warns before the Personal API key expires."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CONF_KEY_EXPIRES, DOMAIN, KEY_EXPIRY_WARNING


def key_expires_at(entry: ConfigEntry) -> datetime | None:
    """When the stored API key expires, as chosen when the key was entered."""
    raw = entry.data.get(CONF_KEY_EXPIRES)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def update_key_expiry_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create or remove the "key expires soon" repair issue for this entry."""
    issue_id = f"key_expiring_{entry.entry_id}"
    expires = key_expires_at(entry)
    if expires is None or expires - datetime.now(UTC) > KEY_EXPIRY_WARNING:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="key_expiring",
        translation_placeholders={
            "account": entry.title,
            "expires": expires.date().isoformat(),
        },
        learn_more_url="https://connect.garmin.com/app/settings/personalApiToken",
    )
