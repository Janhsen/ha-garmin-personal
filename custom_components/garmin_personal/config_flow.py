"""Config flow: enter the Personal API key, reauth, reconfigure and options.

Account identity: the entry's ``unique_id`` is Garmin's ``userProfileId`` (it appears in
the daily summary, even for days without data). It never comes from the name typed into
the form or from the display name, which Garmin lets the user change. Entries made
before config entry 1.2 used the display name; they are moved over on their first
successful setup or reauth (see ``__init__``).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .api import GarminAuthError, GarminError, GarminPersonalApi
from .const import (
    ACCOUNT_ID_LEGACY,
    ACCOUNT_ID_PROFILE,
    CONF_ACCOUNT_ID_KNOWN,
    CONF_ACCOUNT_ID_SOURCE,
    CONF_ACCOUNT_NAME,
    CONF_API_KEY,
    CONF_KEY_EXPIRES,
    CONF_KEY_VALIDITY,
    DEFAULT_DAILY_INTERVAL,
    DEFAULT_KEY_VALIDITY,
    DEFAULT_SYNC_STALE_HOURS,
    DOMAIN,
    ENTRY_MINOR_VERSION,
    ENTRY_VERSION,
    KEY_CREATE_URL,
    KEY_VALIDITY_CHOICES,
    OPT_DAILY_INTERVAL,
    OPT_HOURLY_STATS,
    OPT_INTRADAY,
    OPT_SYNC_STALE_HOURS,
)
from .coordinator import GarminConfigEntry
from .repairs import key_expires_at

_LOGGER = logging.getLogger(__name__)

# Profile fields the unique_id of entries before 1.2 was taken from (first hit wins).
# Only used to recognise those entries again; never to create new identities.
LEGACY_ID_FIELDS = ("userId", "userProfilePk", "id", "displayName", "userName")


@dataclass(frozen=True)
class Account:
    """Who a key belongs to."""

    profile_id: str  # Garmin userProfileId: the new, stable identity
    legacy_id: str | None  # what entries before 1.2 stored as unique_id


def _key_field() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _validity_field() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=list(KEY_VALIDITY_CHOICES),
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="key_validity",
        )
    )


def _expiry(validity_days: str) -> str:
    """Calculated from what the user says; Garmin does not report the expiry."""
    return (datetime.now(UTC) + timedelta(days=int(validity_days))).isoformat()


def _legacy_account_id(profile: Mapping[str, Any]) -> str | None:
    for field in LEGACY_ID_FIELDS:
        value = profile.get(field)
        if value not in (None, ""):
            return str(value)
    return None


def _profile_id(summary: Any) -> str | None:
    if not isinstance(summary, Mapping):
        return None
    value = summary.get("userProfileId")
    return None if value in (None, "") else str(value)


def _same_account(entry: GarminConfigEntry, account: Account) -> bool:
    """Does the new key belong to the account this entry was made for?"""
    if entry.unique_id is None or entry.unique_id == account.profile_id:
        return True
    if entry.data.get(CONF_ACCOUNT_ID_SOURCE, ACCOUNT_ID_LEGACY) == ACCOUNT_ID_PROFILE:
        return False
    # Legacy entry that has not been moved to the profile id yet.
    if not entry.data.get(CONF_ACCOUNT_ID_KNOWN):
        return True  # it never had a profile-based id, so there is nothing to compare
    return account.legacy_id is not None and account.legacy_id == entry.unique_id


class GarminConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Garmin account with a Personal API key."""

    VERSION = ENTRY_VERSION
    MINOR_VERSION = ENTRY_MINOR_VERSION

    async def _identify(self, key: str) -> tuple[Account | None, str | None]:
        """Check the key and find out whose it is. Returns (account, error)."""
        try:
            api = GarminPersonalApi(async_get_clientsession(self.hass), key)
            profile = await api.async_validate()
            summary = await api.get_daily_summary(dt_util.now().date())
        except GarminAuthError:
            return None, "invalid_auth"
        except GarminError:
            return None, "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error while validating the Garmin key")
            return None, "unknown"
        profile_id = _profile_id(summary)
        if profile_id is None:
            return None, "account_id_missing"
        legacy = _legacy_account_id(profile) if isinstance(profile, Mapping) else None
        return Account(profile_id=profile_id, legacy_id=legacy), None

    def _is_known_legacy_account(self, account: Account) -> bool:
        """Is this account already set up under an old (display-name based) unique_id?"""
        if account.legacy_id is None:
            return False
        return any(
            entry.unique_id == account.legacy_id
            and entry.data.get(CONF_ACCOUNT_ID_SOURCE, ACCOUNT_ID_LEGACY) == ACCOUNT_ID_LEGACY
            and entry.data.get(CONF_ACCOUNT_ID_KNOWN)
            for entry in self._async_current_entries(include_ignore=False)
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """First step: name, key and the validity chosen when the key was created."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_ACCOUNT_NAME].strip()
            key = user_input[CONF_API_KEY].strip()
            if not name:
                errors[CONF_ACCOUNT_NAME] = "name_required"
            else:
                account, error = await self._identify(key)
                if error or account is None:
                    errors["base"] = error or "unknown"
                else:
                    await self.async_set_unique_id(account.profile_id)
                    self._abort_if_unique_id_configured()
                    if self._is_known_legacy_account(account):
                        return self.async_abort(reason="already_configured")
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_ACCOUNT_ID_SOURCE: ACCOUNT_ID_PROFILE,
                            CONF_API_KEY: key,
                            CONF_KEY_VALIDITY: user_input[CONF_KEY_VALIDITY],
                            CONF_KEY_EXPIRES: _expiry(user_input[CONF_KEY_VALIDITY]),
                        },
                    )
        previous = user_input or {}
        name_marker = (
            vol.Required(CONF_ACCOUNT_NAME, default=previous[CONF_ACCOUNT_NAME])
            if previous.get(CONF_ACCOUNT_NAME)
            else vol.Required(CONF_ACCOUNT_NAME)
        )
        schema = vol.Schema(
            {
                name_marker: str,
                vol.Required(CONF_API_KEY): _key_field(),
                vol.Required(
                    CONF_KEY_VALIDITY, default=previous.get(CONF_KEY_VALIDITY, DEFAULT_KEY_VALIDITY)
                ): _validity_field(),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"key_url": KEY_CREATE_URL},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The key expired or was revoked."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new key."""
        return await self._replace_key("reauth_confirm", self._get_reauth_entry(), user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the key before it expires."""
        return await self._replace_key("reconfigure", self._get_reconfigure_entry(), user_input)

    def _id_taken_by_other(self, entry: GarminConfigEntry, profile_id: str) -> bool:
        return any(
            other.entry_id != entry.entry_id and other.unique_id == profile_id
            for other in self._async_current_entries(include_ignore=False)
        )

    async def _replace_key(
        self, step_id: str, entry: GarminConfigEntry, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        remembered = str(entry.data.get(CONF_KEY_VALIDITY, DEFAULT_KEY_VALIDITY))
        if remembered not in KEY_VALIDITY_CHOICES:
            remembered = DEFAULT_KEY_VALIDITY
        chosen = (user_input or {}).get(CONF_KEY_VALIDITY, remembered)
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            account, error = await self._identify(key)
            if error or account is None:
                errors["base"] = error or "unknown"
            elif not _same_account(entry, account):
                return self.async_abort(reason="wrong_account")
            else:
                updates: dict[str, Any] = {
                    CONF_API_KEY: key,
                    CONF_KEY_VALIDITY: user_input[CONF_KEY_VALIDITY],
                    CONF_KEY_EXPIRES: _expiry(user_input[CONF_KEY_VALIDITY]),
                }
                extra: dict[str, Any] = {}
                if (
                    entry.data.get(CONF_ACCOUNT_ID_SOURCE, ACCOUNT_ID_LEGACY) != ACCOUNT_ID_PROFILE
                    and not self._id_taken_by_other(entry, account.profile_id)
                ):
                    updates[CONF_ACCOUNT_ID_SOURCE] = ACCOUNT_ID_PROFILE
                    extra["unique_id"] = account.profile_id
                # The entry has no update listener, so this is the only reload.
                return self.async_update_reload_and_abort(entry, data_updates=updates, **extra)
        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): _key_field(),
                vol.Required(CONF_KEY_VALIDITY, default=chosen): _validity_field(),
            }
        )
        expires = key_expires_at(entry)
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "account": entry.title,
                "expires": expires.date().isoformat() if expires else "?",
                "key_url": KEY_CREATE_URL,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: GarminConfigEntry) -> GarminOptionsFlow:
        """Options dialog."""
        return GarminOptionsFlow()


class GarminOptionsFlow(OptionsFlowWithReload):
    """Update interval, intraday attributes, hourly statistics and the sync-stale threshold.

    Reloads the entry by itself when the options change.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    OPT_DAILY_INTERVAL: int(user_input[OPT_DAILY_INTERVAL]),
                    OPT_INTRADAY: user_input[OPT_INTRADAY],
                    OPT_HOURLY_STATS: user_input.get(OPT_HOURLY_STATS, True),
                    OPT_SYNC_STALE_HOURS: int(user_input[OPT_SYNC_STALE_HOURS]),
                }
            )
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    OPT_DAILY_INTERVAL, default=options.get(OPT_DAILY_INTERVAL, DEFAULT_DAILY_INTERVAL)
                ): NumberSelector(
                    NumberSelectorConfig(min=5, max=240, step=5, mode=NumberSelectorMode.BOX,
                                         unit_of_measurement="min")
                ),
                vol.Required(OPT_INTRADAY, default=options.get(OPT_INTRADAY, False)): bool,
                vol.Required(OPT_HOURLY_STATS, default=options.get(OPT_HOURLY_STATS, True)): bool,
                vol.Required(
                    OPT_SYNC_STALE_HOURS, default=options.get(OPT_SYNC_STALE_HOURS, DEFAULT_SYNC_STALE_HOURS)
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=168, step=1, mode=NumberSelectorMode.BOX,
                                         unit_of_measurement="h")
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
