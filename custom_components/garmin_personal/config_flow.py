"""Config flow: enter the Personal API key, reauth and options."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
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

from .api import GarminAuthError, GarminError, GarminPersonalApi
from .const import (
    CONF_API_KEY,
    CONF_KEY_EXPIRES,
    CONF_KEY_VALIDITY,
    DEFAULT_DAILY_INTERVAL,
    DEFAULT_SYNC_STALE_HOURS,
    DOMAIN,
    KEY_VALIDITY_CHOICES,
    OPT_DAILY_INTERVAL,
    OPT_INTRADAY,
    OPT_SYNC_STALE_HOURS,
)
from .coordinator import GarminConfigEntry

_LOGGER = logging.getLogger(__name__)

CONF_NAME = "name"
CONF_ACCOUNT_ID_KNOWN = "account_id_known"
ID_FIELDS = ("userId", "userProfilePk", "id", "displayName", "userName")


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
    return (datetime.now(UTC) + timedelta(days=int(validity_days))).isoformat()


def _account_id(profile: Mapping[str, Any]) -> str | None:
    for field in ID_FIELDS:
        value = profile.get(field)
        if value not in (None, ""):
            return str(value)
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "garmin"


class GarminConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Garmin account with a Personal API key."""

    VERSION = 1

    async def _check_key(self, key: str) -> tuple[dict[str, Any] | None, str | None]:
        """Return (profile, error)."""
        try:
            api = GarminPersonalApi(async_get_clientsession(self.hass), key)
            return await api.async_validate(), None
        except GarminAuthError:
            return None, "invalid_auth"
        except GarminError:
            return None, "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error while validating the Garmin key")
            return None, "unknown"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """First step: name, key and the validity chosen when the key was created."""
        errors: dict[str, str] = {}
        if user_input is not None:
            profile, error = await self._check_key(user_input[CONF_API_KEY])
            if error or profile is None:
                errors["base"] = error or "unknown"
            else:
                name = user_input[CONF_NAME].strip() or "Garmin"
                account_id = _account_id(profile)
                await self.async_set_unique_id(account_id or _slug(name))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_ACCOUNT_ID_KNOWN: account_id is not None,
                        CONF_API_KEY: user_input[CONF_API_KEY].strip(),
                        CONF_KEY_VALIDITY: user_input[CONF_KEY_VALIDITY],
                        CONF_KEY_EXPIRES: _expiry(user_input[CONF_KEY_VALIDITY]),
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=(user_input or {}).get(CONF_NAME, "Garmin")): str,
                vol.Required(CONF_API_KEY): _key_field(),
                vol.Required(CONF_KEY_VALIDITY, default="365"): _validity_field(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

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

    async def _replace_key(
        self, step_id: str, entry: GarminConfigEntry, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            profile, error = await self._check_key(user_input[CONF_API_KEY])
            if error or profile is None:
                errors["base"] = error or "unknown"
            else:
                new_id = _account_id(profile)
                if new_id and entry.unique_id and new_id != entry.unique_id and entry.data.get(CONF_ACCOUNT_ID_KNOWN):
                    return self.async_abort(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_API_KEY: user_input[CONF_API_KEY].strip(),
                        CONF_KEY_VALIDITY: user_input[CONF_KEY_VALIDITY],
                        CONF_KEY_EXPIRES: _expiry(user_input[CONF_KEY_VALIDITY]),
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): _key_field(),
                vol.Required(CONF_KEY_VALIDITY, default="365"): _validity_field(),
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
            description_placeholders={"account": entry.title},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: GarminConfigEntry) -> OptionsFlow:
        """Options dialog."""
        return GarminOptionsFlow()


class GarminOptionsFlow(OptionsFlow):
    """Update interval, intraday attributes and the sync-stale threshold."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    OPT_DAILY_INTERVAL: int(user_input[OPT_DAILY_INTERVAL]),
                    OPT_INTRADAY: user_input[OPT_INTRADAY],
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
                vol.Required(
                    OPT_SYNC_STALE_HOURS, default=options.get(OPT_SYNC_STALE_HOURS, DEFAULT_SYNC_STALE_HOURS)
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=168, step=1, mode=NumberSelectorMode.BOX,
                                         unit_of_measurement="h")
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
