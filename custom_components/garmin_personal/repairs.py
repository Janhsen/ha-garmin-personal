"""Repair issue that warns before the Personal API key expires.

Garmin does not report when a key expires. The date used here is calculated from the
validity the user entered when the key was added (or replaced), so the issue texts say
"calculated from your input". Before the date the issue is a warning, after it an error.
"""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CONF_KEY_EXPIRES, DOMAIN, KEY_CREATE_URL, KEY_EXPIRY_WARNING


def key_expires_at(entry: ConfigEntry) -> datetime | None:
    """When the stored API key expires, as calculated from the validity the user entered."""
    raw = entry.data.get(CONF_KEY_EXPIRES)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def expiry_issue_id(entry: ConfigEntry) -> str:
    """Issue id for one entry."""
    return f"key_expiring_{entry.entry_id}"


def update_key_expiry_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create, update or remove the "key expires soon / has expired" repair issue."""
    issue_id = expiry_issue_id(entry)
    expires = key_expires_at(entry)
    now = datetime.now(UTC)
    if expires is None or expires - now > KEY_EXPIRY_WARNING:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    expired = expires <= now
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR if expired else ir.IssueSeverity.WARNING,
        translation_key="key_expired" if expired else "key_expiring",
        translation_placeholders={
            "account": entry.title,
            "expires": expires.date().isoformat(),
            "days_left": str(max((expires - now).days, 0)),
        },
        learn_more_url=KEY_CREATE_URL,
    )


def remove_key_expiry_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the issue (the entry is being removed)."""
    ir.async_delete_issue(hass, DOMAIN, expiry_issue_id(entry))
