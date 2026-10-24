"""Config flow: Hilfsfunktionen, user-Schritt, Reauth/Reconfigure, Optionen (ohne Home Assistant)."""

import logging
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402

logging.disable(logging.CRITICAL)  # erwartete Fehlerpfade sollen die Testausgabe nicht fluten
gp = stubs.load_full()
cf = sys.modules["gp_full.config_flow"]
const = sys.modules["gp_full.const"]
api_mod = sys.modules["gp_full.api"]


class FakeApi:
    """Ersetzt GarminPersonalApi im config_flow. Verhalten pro Test über Klassenattribute."""

    profile: dict = {"displayName": "example-user"}
    summary: dict | None = {"userProfileId": 4711}
    error: Exception | None = None
    summary_error: Exception | None = None
    keys_seen: list = []

    def __init__(self, session, key):
        FakeApi.keys_seen.append(key)

    async def async_validate(self):
        if FakeApi.error:
            raise FakeApi.error
        return FakeApi.profile

    async def get_daily_summary(self, day):
        if FakeApi.summary_error:
            raise FakeApi.summary_error
        return FakeApi.summary


class FlowBase(unittest.TestCase):
    def setUp(self):
        stubs.ConfigFlow.configured_unique_ids = set()
        FakeApi.profile = {"displayName": "example-user"}
        FakeApi.summary = {"userProfileId": 4711}
        FakeApi.summary_error = None
        FakeApi.error = None
        FakeApi.keys_seen = []
        self._orig = cf.GarminPersonalApi
        cf.GarminPersonalApi = FakeApi

    def tearDown(self):
        cf.GarminPersonalApi = self._orig

    def flow(self):
        return cf.GarminConfigFlow()


class Helpers(unittest.TestCase):
    def test_legacy_id_prefers_field_order(self):
        self.assertEqual(cf._legacy_account_id({"userId": 5, "displayName": "x"}), "5")
        self.assertEqual(cf._legacy_account_id({"displayName": "x", "userName": "u"}), "x")

    def test_legacy_id_skips_none_and_empty(self):
        self.assertEqual(cf._legacy_account_id({"userId": None, "userProfilePk": "", "id": 9}), "9")
        self.assertEqual(cf._legacy_account_id({"userId": 0}), "0")
        self.assertIsNone(cf._legacy_account_id({}))

    def test_profile_id_from_summary(self):
        self.assertEqual(cf._profile_id({"userProfileId": 12}), "12")
        self.assertIsNone(cf._profile_id({"userProfileId": None}))
        self.assertIsNone(cf._profile_id({"userProfileId": ""}))
        self.assertIsNone(cf._profile_id(None))
        self.assertIsNone(cf._profile_id([]))

    def test_expiry_is_utc_iso_in_the_future(self):
        before = datetime.now(UTC)
        value = datetime.fromisoformat(cf._expiry("30"))
        self.assertIsNotNone(value.tzinfo)
        self.assertAlmostEqual((value - before).total_seconds(), timedelta(days=30).total_seconds(), delta=5)

    def test_expiry_all_choices(self):
        for choice in const.KEY_VALIDITY_CHOICES:
            self.assertGreater(datetime.fromisoformat(cf._expiry(choice)), datetime.now(UTC))


class UserStep(FlowBase):
    INPUT = {"name": " Jan ", "api_key": "  KEY  ", "key_validity_days": "90"}

    def test_form_shown_first_with_defaults(self):
        result = stubs.run(self.flow().async_step_user())
        self.assertEqual((result["type"], result["step_id"]), ("form", "user"))
        schema = result["data_schema"]
        self.assertEqual(set(schema.keys()), {"name", "api_key", "key_validity_days"})
        self.assertIsNone(schema.default_of("name"))  # the name is never guessed
        self.assertEqual(schema.default_of("key_validity_days"), "365")
        self.assertEqual(set(result["description_placeholders"]), {"key_url"})

    def test_valid_key_creates_entry(self):
        flow = self.flow()
        result = stubs.run(flow.async_step_user(dict(self.INPUT)))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["title"], "Jan")  # getrimmt
        data = result["data"]
        self.assertEqual(data["api_key"], "KEY")  # gespeichert getrimmt
        self.assertEqual(data["account_id_source"], "profile_id")
        self.assertNotIn("account_id_known", data)
        self.assertEqual(data["key_validity_days"], "90")
        self.assertGreater(datetime.fromisoformat(data["key_expires_at"]), datetime.now(UTC))
        self.assertEqual(flow.unique_id, "4711")

    def test_blank_name_is_an_error(self):
        result = stubs.run(self.flow().async_step_user({**self.INPUT, "name": "   "}))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"name": "name_required"})
        self.assertEqual(FakeApi.keys_seen, [])

    def test_unique_id_never_comes_from_name_or_display_name(self):
        FakeApi.profile = {"displayName": "Someone"}
        flow = self.flow()
        stubs.run(flow.async_step_user({**self.INPUT, "name": "Mein Konto"}))
        self.assertEqual(flow.unique_id, "4711")

    def test_no_profile_id_is_an_error(self):
        for summary in ({}, {"userProfileId": None}, None):
            FakeApi.summary = summary
            result = stubs.run(self.flow().async_step_user(dict(self.INPUT)))
            self.assertEqual(result["errors"], {"base": "account_id_missing"}, summary)

    def test_summary_failure_maps_to_errors(self):
        for exc, code in ((api_mod.GarminAuthError("x"), "invalid_auth"),
                          (api_mod.GarminApiError("x", 500), "cannot_connect")):
            FakeApi.summary_error = exc
            result = stubs.run(self.flow().async_step_user(dict(self.INPUT)))
            self.assertEqual(result["errors"], {"base": code})

    def test_legacy_entry_of_same_account_counts_as_duplicate(self):
        FakeApi.profile = {"displayName": "example-user"}
        old = stubs.FakeEntry(unique_id="example-user",
                              data={"account_id_known": True, "account_id_source": "legacy"})
        flow = self.flow()
        flow.hass.config_entries.entries.append(old)
        result = stubs.run(flow.async_step_user(dict(self.INPUT)))
        self.assertEqual(result, {"type": "abort", "reason": "already_configured"})

    def test_invalid_auth(self):
        FakeApi.error = api_mod.GarminAuthError("nope")
        result = stubs.run(self.flow().async_step_user(dict(self.INPUT)))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"base": "invalid_auth"})

    def test_cannot_connect_for_other_garmin_errors(self):
        for exc in (api_mod.GarminApiError("x", 500), api_mod.GarminRateLimitError("429")):
            FakeApi.error = exc
            result = stubs.run(self.flow().async_step_user(dict(self.INPUT)))
            self.assertEqual(result["errors"], {"base": "cannot_connect"}, exc)

    def test_unknown_for_unexpected_exception(self):
        FakeApi.error = RuntimeError("boom")
        result = stubs.run(self.flow().async_step_user(dict(self.INPUT)))
        self.assertEqual(result["errors"], {"base": "unknown"})

    def test_form_after_error_keeps_entered_name(self):
        FakeApi.error = api_mod.GarminAuthError("nope")
        result = stubs.run(self.flow().async_step_user({**self.INPUT, "name": "Katrin"}))
        self.assertEqual(result["data_schema"].default_of("name"), "Katrin")
        self.assertEqual(result["data_schema"].default_of("key_validity_days"), "90")

    def test_duplicate_account_aborts(self):
        stubs.ConfigFlow.configured_unique_ids = {"4711"}
        with self.assertRaises(stubs.AbortFlow) as ctx:
            stubs.run(self.flow().async_step_user(dict(self.INPUT)))
        self.assertEqual(ctx.exception.reason, "already_configured")

    def test_empty_key_is_invalid_auth_with_real_api_class(self):
        # Der echte Konstruktor lehnt leere Schlüssel ab; der Flow muss das als invalid_auth zeigen.
        cf.GarminPersonalApi = self._orig
        result = stubs.run(self.flow().async_step_user({**self.INPUT, "api_key": "   "}))
        self.assertEqual(result["errors"], {"base": "invalid_auth"})

    def test_key_is_validated_exactly_as_stored(self):
        """Gültigkeit und gespeicherter Schlüssel sollten übereinstimmen (getrimmt)."""
        stubs.run(self.flow().async_step_user(dict(self.INPUT)))
        # Das Produktivcode übergibt den ungetrimmten Wert an den Client (der trimmt selbst).
        self.assertEqual(FakeApi.keys_seen[0].strip(), "KEY")


class ReplaceKey(FlowBase):
    def entry(self, unique_id="4711", title="Jan", **data):
        base = {"account_id_source": "profile_id", "api_key": "OLD", "key_validity_days": "90"}
        base.update(data)
        return stubs.FakeEntry(title=title, unique_id=unique_id, data=base)

    def flow_for(self, entry, kind):
        flow = self.flow()
        if kind == "reauth":
            flow.reauth_entry = entry
        else:
            flow.reconfigure_entry = entry
        return flow

    INPUT = {"api_key": " NEW ", "key_validity_days": "180"}

    def test_reauth_entry_point_shows_confirm_form(self):
        entry = self.entry()
        flow = self.flow_for(entry, "reauth")
        result = stubs.run(flow.async_step_reauth({}))
        self.assertEqual((result["type"], result["step_id"]), ("form", "reauth_confirm"))
        self.assertEqual(set(result["description_placeholders"]), {"account", "expires", "key_url"})
        self.assertEqual(result["description_placeholders"]["account"], "Jan")

    def test_reconfigure_form(self):
        result = stubs.run(self.flow_for(self.entry(), "reconfigure").async_step_reconfigure())
        self.assertEqual(result["step_id"], "reconfigure")
        self.assertEqual(set(result["data_schema"].keys()), {"api_key", "key_validity_days"})

    def test_reauth_same_account_updates_data(self):
        entry = self.entry()
        flow = self.flow_for(entry, "reauth")
        result = stubs.run(flow.async_step_reauth_confirm(dict(self.INPUT)))
        self.assertEqual(result["reason"], "update_reload")
        upd = result["data_updates"]
        self.assertEqual(upd["api_key"], "NEW")
        self.assertEqual(upd["key_validity_days"], "180")
        self.assertGreater(datetime.fromisoformat(upd["key_expires_at"]),
                           datetime.now(UTC) + timedelta(days=179))
        self.assertNotIn("account_id_source", upd)  # already on the profile id
        self.assertEqual(flow.update_kwargs, [{}])

    def test_reconfigure_same_account_updates_data(self):
        flow = self.flow_for(self.entry(), "reconfigure")
        result = stubs.run(flow.async_step_reconfigure(dict(self.INPUT)))
        self.assertEqual(result["reason"], "update_reload")

    def test_wrong_account_aborts(self):
        FakeApi.summary = {"userProfileId": 999}
        for kind, step in (("reauth", "async_step_reauth_confirm"), ("reconfigure", "async_step_reconfigure")):
            flow = self.flow_for(self.entry(), kind)
            result = stubs.run(getattr(flow, step)(dict(self.INPUT)))
            self.assertEqual(result, {"type": "abort", "reason": "wrong_account"}, kind)
            self.assertEqual(flow.updates, [])

    def test_legacy_entry_with_other_profile_id_but_same_display_name_is_accepted_and_migrated(self):
        entry = self.entry(unique_id="example-user", account_id_source="legacy", account_id_known=True)
        flow = self.flow_for(entry, "reauth")
        result = stubs.run(flow.async_step_reauth_confirm(dict(self.INPUT)))
        self.assertEqual(result["reason"], "update_reload")
        self.assertEqual(result["data_updates"]["account_id_source"], "profile_id")
        self.assertEqual(flow.update_kwargs, [{"unique_id": "4711"}])

    def test_legacy_entry_with_renamed_display_name_is_refused(self):
        FakeApi.profile = {"displayName": "renamed"}
        entry = self.entry(unique_id="example-user", account_id_source="legacy", account_id_known=True)
        result = stubs.run(self.flow_for(entry, "reauth").async_step_reauth_confirm(dict(self.INPUT)))
        self.assertEqual(result, {"type": "abort", "reason": "wrong_account"})

    def test_legacy_entry_that_never_had_an_id_is_accepted(self):
        FakeApi.profile = {}
        entry = self.entry(unique_id="mein-konto", account_id_source="legacy", account_id_known=False)
        result = stubs.run(self.flow_for(entry, "reauth").async_step_reauth_confirm(dict(self.INPUT)))
        self.assertEqual(result["reason"], "update_reload")

    def test_legacy_entry_not_moved_when_another_entry_has_the_id(self):
        other = stubs.FakeEntry(entry_id="E2", unique_id="4711")
        entry = self.entry(unique_id="example-user", account_id_source="legacy", account_id_known=True)
        flow = self.flow_for(entry, "reauth")
        flow.hass.config_entries.entries.extend([entry, other])
        result = stubs.run(flow.async_step_reauth_confirm(dict(self.INPUT)))
        self.assertEqual(result["reason"], "update_reload")
        self.assertEqual(flow.update_kwargs, [{}])
        self.assertNotIn("account_id_source", result["data_updates"])

    def test_form_default_validity_is_the_last_chosen(self):
        for kind, step in (("reauth", "async_step_reauth_confirm"), ("reconfigure", "async_step_reconfigure")):
            flow = self.flow_for(self.entry(key_validity_days="30"), kind)
            result = stubs.run(getattr(flow, step)())
            self.assertEqual(result["data_schema"].default_of("key_validity_days"), "30", kind)

    def test_form_default_falls_back_when_stored_value_is_unusable(self):
        for stored in ("7", None):
            data = {} if stored is None else {"key_validity_days": stored}
            entry = stubs.FakeEntry(unique_id="4711", data={"account_id_source": "profile_id", **data})
            result = stubs.run(self.flow_for(entry, "reauth").async_step_reauth_confirm())
            self.assertEqual(result["data_schema"].default_of("key_validity_days"), "365")

    def test_error_keeps_the_validity_the_user_chose(self):
        FakeApi.error = api_mod.GarminAuthError("x")
        result = stubs.run(self.flow_for(self.entry(key_validity_days="30"), "reauth")
                           .async_step_reauth_confirm(dict(self.INPUT)))
        self.assertEqual(result["data_schema"].default_of("key_validity_days"), "180")

    def test_missing_profile_id_in_new_key_is_an_error(self):
        FakeApi.summary = {}
        result = stubs.run(self.flow_for(self.entry(), "reauth").async_step_reauth_confirm(dict(self.INPUT)))
        self.assertEqual(result["errors"], {"base": "account_id_missing"})

    def test_entry_without_unique_id_is_accepted(self):
        result = stubs.run(self.flow_for(self.entry(unique_id=None), "reauth")
                           .async_step_reauth_confirm(dict(self.INPUT)))
        self.assertEqual(result["reason"], "update_reload")

    def test_errors_keep_form_open(self):
        for exc, code in ((api_mod.GarminAuthError("x"), "invalid_auth"),
                          (api_mod.GarminApiError("x"), "cannot_connect"),
                          (RuntimeError("x"), "unknown")):
            FakeApi.error = exc
            result = stubs.run(self.flow_for(self.entry(), "reauth").async_step_reauth_confirm(dict(self.INPUT)))
            self.assertEqual((result["type"], result["step_id"], result["errors"]),
                             ("form", "reauth_confirm", {"base": code}))


class Options(unittest.TestCase):
    def flow(self, options=None):
        flow = cf.GarminOptionsFlow()
        flow.config_entry = stubs.FakeEntry(options=options)
        return flow

    def test_factory_returns_options_flow(self):
        self.assertIsInstance(cf.GarminConfigFlow.async_get_options_flow(stubs.FakeEntry()), cf.GarminOptionsFlow)

    def test_options_flow_reloads_by_itself(self):
        self.assertTrue(issubclass(cf.GarminOptionsFlow, stubs.OptionsFlowWithReload))

    def test_form_defaults(self):
        result = stubs.run(self.flow().async_step_init())
        schema = result["data_schema"]
        self.assertEqual(schema.default_of(const.OPT_DAILY_INTERVAL), const.DEFAULT_DAILY_INTERVAL)
        self.assertIs(schema.default_of(const.OPT_INTRADAY), False)
        self.assertIs(schema.default_of(const.OPT_HOURLY_STATS), True)  # on by default
        self.assertIs(schema.default_of(const.OPT_HISTORY_AUTO), True)
        self.assertEqual(schema.default_of(const.OPT_SYNC_STALE_HOURS), const.DEFAULT_SYNC_STALE_HOURS)

    def test_form_uses_stored_options(self):
        result = stubs.run(self.flow({const.OPT_DAILY_INTERVAL: 15, const.OPT_INTRADAY: True,
                                      const.OPT_SYNC_STALE_HOURS: 6}).async_step_init())
        schema = result["data_schema"]
        self.assertEqual(schema.default_of(const.OPT_DAILY_INTERVAL), 15)
        self.assertIs(schema.default_of(const.OPT_INTRADAY), True)
        self.assertEqual(schema.default_of(const.OPT_SYNC_STALE_HOURS), 6)

    def test_submit_coerces_numbers_to_int(self):
        result = stubs.run(self.flow().async_step_init(
            {const.OPT_DAILY_INTERVAL: 10.0, const.OPT_INTRADAY: True, const.OPT_SYNC_STALE_HOURS: 24.0}))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"], {const.OPT_DAILY_INTERVAL: 10, const.OPT_INTRADAY: True,
                                          const.OPT_HOURLY_STATS: True, const.OPT_HISTORY_AUTO: True,
                                          const.OPT_SYNC_STALE_HOURS: 24})
        self.assertIsInstance(result["data"][const.OPT_DAILY_INTERVAL], int)


if __name__ == "__main__":
    unittest.main()
