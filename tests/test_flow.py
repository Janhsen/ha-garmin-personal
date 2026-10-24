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

    profile: dict = {"userId": 4711}
    error: Exception | None = None
    keys_seen: list = []

    def __init__(self, session, key):
        FakeApi.keys_seen.append(key)

    async def async_validate(self):
        if FakeApi.error:
            raise FakeApi.error
        return FakeApi.profile


class FlowBase(unittest.TestCase):
    def setUp(self):
        stubs.ConfigFlow.configured_unique_ids = set()
        FakeApi.profile = {"userId": 4711}
        FakeApi.error = None
        FakeApi.keys_seen = []
        self._orig = cf.GarminPersonalApi
        cf.GarminPersonalApi = FakeApi

    def tearDown(self):
        cf.GarminPersonalApi = self._orig

    def flow(self):
        return cf.GarminConfigFlow()


class Helpers(unittest.TestCase):
    def test_account_id_prefers_field_order(self):
        self.assertEqual(cf._account_id({"userId": 5, "displayName": "x"}), "5")
        self.assertEqual(cf._account_id({"displayName": "x", "userName": "u"}), "x")

    def test_account_id_skips_none_and_empty(self):
        self.assertEqual(cf._account_id({"userId": None, "userProfilePk": "", "id": 9}), "9")

    def test_account_id_zero_is_a_valid_id(self):
        self.assertEqual(cf._account_id({"userId": 0}), "0")

    def test_account_id_none_when_nothing(self):
        self.assertIsNone(cf._account_id({}))
        self.assertIsNone(cf._account_id({"foo": 1}))

    def test_slug(self):
        self.assertEqual(cf._slug("Jan Janhsen"), "jan-janhsen")
        self.assertEqual(cf._slug("  --A__B--  "), "a-b")
        self.assertEqual(cf._slug("äöü"), "garmin")
        self.assertEqual(cf._slug(""), "garmin")

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
        self.assertEqual(schema.default_of("name"), "Garmin")
        self.assertEqual(schema.default_of("key_validity_days"), "365")

    def test_valid_key_creates_entry(self):
        flow = self.flow()
        result = stubs.run(flow.async_step_user(dict(self.INPUT)))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["title"], "Jan")  # getrimmt
        data = result["data"]
        self.assertEqual(data["api_key"], "KEY")  # gespeichert getrimmt
        self.assertTrue(data["account_id_known"])
        self.assertEqual(data["key_validity_days"], "90")
        self.assertGreater(datetime.fromisoformat(data["key_expires_at"]), datetime.now(UTC))
        self.assertEqual(flow.unique_id, "4711")

    def test_blank_name_falls_back_to_garmin(self):
        result = stubs.run(self.flow().async_step_user({**self.INPUT, "name": "   "}))
        self.assertEqual(result["title"], "Garmin")

    def test_unknown_account_id_uses_slug_of_name(self):
        FakeApi.profile = {}
        flow = self.flow()
        result = stubs.run(flow.async_step_user({**self.INPUT, "name": "Mein Konto"}))
        self.assertEqual(flow.unique_id, "mein-konto")
        self.assertFalse(result["data"]["account_id_known"])

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
    def entry(self, unique_id="4711", known=True, title="Jan"):
        return stubs.FakeEntry(title=title, unique_id=unique_id,
                               data={"account_id_known": known, "api_key": "OLD"})

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
        self.assertEqual(result["description_placeholders"], {"account": "Jan"})

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
        self.assertNotIn("account_id_known", upd)

    def test_reconfigure_same_account_updates_data(self):
        flow = self.flow_for(self.entry(), "reconfigure")
        result = stubs.run(flow.async_step_reconfigure(dict(self.INPUT)))
        self.assertEqual(result["reason"], "update_reload")

    def test_wrong_account_aborts(self):
        FakeApi.profile = {"userId": 999}
        for kind, step in (("reauth", "async_step_reauth_confirm"), ("reconfigure", "async_step_reconfigure")):
            flow = self.flow_for(self.entry(), kind)
            result = stubs.run(getattr(flow, step)(dict(self.INPUT)))
            self.assertEqual(result, {"type": "abort", "reason": "wrong_account"}, kind)
            self.assertEqual(flow.updates, [])

    def test_different_id_allowed_when_old_id_was_only_a_slug(self):
        FakeApi.profile = {"userId": 999}
        entry = self.entry(unique_id="mein-konto", known=False)
        result = stubs.run(self.flow_for(entry, "reauth").async_step_reauth_confirm(dict(self.INPUT)))
        self.assertEqual(result["reason"], "update_reload")

    def test_no_id_in_new_profile_is_accepted(self):
        FakeApi.profile = {}
        result = stubs.run(self.flow_for(self.entry(), "reauth").async_step_reauth_confirm(dict(self.INPUT)))
        self.assertEqual(result["reason"], "update_reload")

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

    def test_form_defaults(self):
        result = stubs.run(self.flow().async_step_init())
        schema = result["data_schema"]
        self.assertEqual(schema.default_of(const.OPT_DAILY_INTERVAL), const.DEFAULT_DAILY_INTERVAL)
        self.assertIs(schema.default_of(const.OPT_INTRADAY), False)
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
                                          const.OPT_SYNC_STALE_HOURS: 24})
        self.assertIsInstance(result["data"][const.OPT_DAILY_INTERVAL], int)


if __name__ == "__main__":
    unittest.main()
