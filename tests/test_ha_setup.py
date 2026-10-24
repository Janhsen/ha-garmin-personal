"""Lifecycle in __init__.py: setup, expiry timer, unique_id adoption, migration, removal.

Runs against the stubs in stubs.py, so it checks our wiring, not Home Assistant itself.
All ids, names and keys below are invented.
"""

import logging
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402

logging.disable(logging.CRITICAL)
gp = stubs.load_full()
const = sys.modules["gp_full.const"]
api_mod = sys.modules["gp_full.api"]
DOMAIN = "garmin_personal"


class FakeApi:
    """Every endpoint answers ``None``, except the daily summary."""

    summary = {"userProfileId": 4711}
    raise_on_init: Exception | None = None

    def __init__(self, session, key):
        if FakeApi.raise_on_init:
            raise FakeApi.raise_on_init
        self.key = key

    async def get_daily_summary(self, day):
        return FakeApi.summary

    def __getattr__(self, name):
        async def answer(*args, **kwargs):
            return None

        return answer


def expiry(days):
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def make_entry(unique_id="example-user", source="legacy", days=300, **extra):
    data = {"api_key": "KEY", "key_validity_days": "365", "key_expires_at": expiry(days),
            "account_id_known": True}
    if source is not None:
        data["account_id_source"] = source
    data.update(extra)
    return stubs.FakeEntry(entry_id="E1", title="Alex", data=data, unique_id=unique_id)


class Base(unittest.TestCase):
    def setUp(self):
        stubs.ISSUES.clear()
        stubs.TIMERS.clear()
        stubs.REGISTRY.entries.clear()
        FakeApi.summary = {"userProfileId": 4711}
        FakeApi.raise_on_init = None
        self._orig = gp.GarminPersonalApi
        gp.GarminPersonalApi = FakeApi
        self.hass = stubs.FakeHass()

    def tearDown(self):
        gp.GarminPersonalApi = self._orig

    def setup(self, entry):
        self.hass.config_entries.entries.append(entry)
        return stubs.run(gp.async_setup_entry(self.hass, entry))


class Setup(Base):
    def test_setup_succeeds_and_forwards_all_platforms(self):
        entry = make_entry(source="profile_id", unique_id="4711")
        self.assertTrue(self.setup(entry))
        self.assertEqual(set(entry.runtime_data.coordinators),
                         {"daily", "sleep", "body", "activities", "profile"})
        self.assertEqual(self.hass.config_entries.forwarded, [(entry, list(gp.PLATFORMS))])

    def test_no_update_listener_and_no_options_copy(self):
        entry = make_entry(source="profile_id", unique_id="4711")
        entry.add_update_listener = lambda cb: self.fail("update listener registered")
        self.setup(entry)

    def test_hourly_expiry_check_is_registered_and_released(self):
        entry = make_entry(source="profile_id", unique_id="4711", days=300)
        self.setup(entry)
        self.assertEqual(len(stubs.TIMERS), 1)
        timer = stubs.TIMERS[0]
        self.assertEqual(timer["interval"], const.KEY_EXPIRY_CHECK_INTERVAL)
        self.assertLessEqual(timer["interval"], timedelta(days=1))
        self.assertEqual(stubs.ISSUES, {})  # far from expiry
        # time passes: the stored date is now close; the timer alone raises the issue
        entry.data = {**entry.data, "key_expires_at": expiry(2)}
        timer["action"](datetime.now(UTC))
        issue = stubs.ISSUES[(DOMAIN, "key_expiring_E1")]
        self.assertEqual(issue["translation_key"], "key_expiring")
        # unloading cancels the timer
        for cb in entry.unload_callbacks:
            cb()
        self.assertTrue(timer["cancelled"])

    def test_empty_key_asks_for_reauth_with_translation(self):
        FakeApi.raise_on_init = api_mod.GarminAuthError("The API key is empty")
        entry = make_entry(source="profile_id", unique_id="4711")
        with self.assertRaises(stubs.ConfigEntryAuthFailed) as ctx:
            self.setup(entry)
        self.assertEqual(ctx.exception.translation_domain, DOMAIN)
        self.assertEqual(ctx.exception.translation_key, "auth_failed")

    def test_unload_hands_the_platforms_back(self):
        entry = make_entry(source="profile_id", unique_id="4711")
        self.assertTrue(stubs.run(gp.async_unload_entry(self.hass, entry)))
        self.assertEqual(self.hass.config_entries.unloaded, [(entry, list(gp.PLATFORMS))])


class AdoptProfileId(Base):
    def test_legacy_entry_is_moved_to_the_profile_id_on_setup(self):
        entry = make_entry()
        self.setup(entry)
        self.assertEqual(entry.unique_id, "4711")
        self.assertEqual(entry.data["account_id_source"], "profile_id")
        self.assertEqual(entry.data["api_key"], "KEY")  # nothing else touched

    def test_entry_without_source_counts_as_legacy(self):
        entry = make_entry(source=None)
        self.setup(entry)
        self.assertEqual(entry.unique_id, "4711")

    def test_already_migrated_entry_is_left_alone(self):
        entry = make_entry(source="profile_id", unique_id="4711")
        FakeApi.summary = {"userProfileId": 999}
        self.setup(entry)
        self.assertEqual(entry.unique_id, "4711")

    def test_no_profile_id_in_summary_keeps_legacy_for_the_next_start(self):
        for summary in ({}, {"userProfileId": None}, None):
            FakeApi.summary = summary
            entry = make_entry()
            self.setup(entry)
            self.assertEqual(entry.unique_id, "example-user", summary)
            self.assertEqual(entry.data["account_id_source"], "legacy")

    def test_not_moved_when_another_entry_already_has_the_id(self):
        other = stubs.FakeEntry(entry_id="E2", unique_id="4711")
        self.hass.config_entries.entries.append(other)
        entry = make_entry()
        self.setup(entry)
        self.assertEqual(entry.unique_id, "example-user")

    def test_unique_id_is_a_string(self):
        FakeApi.summary = {"userProfileId": 12345678}
        entry = make_entry()
        self.setup(entry)
        self.assertEqual(entry.unique_id, "12345678")


class Migrate(Base):
    def test_1_1_becomes_1_2_and_is_marked_legacy_without_network(self):
        entry = make_entry(source=None)
        entry.version, entry.minor_version = 1, 1
        gp.GarminPersonalApi = lambda *a, **k: self.fail("migration must not use the network")
        self.assertTrue(stubs.run(gp.async_migrate_entry(self.hass, entry)))
        self.assertEqual((entry.version, entry.minor_version), (1, 2))
        self.assertEqual(entry.data["account_id_source"], "legacy")
        self.assertEqual(entry.unique_id, "example-user")  # unchanged until setup
        self.assertEqual(entry.data["api_key"], "KEY")

    def test_existing_source_is_kept(self):
        entry = make_entry(source="profile_id", unique_id="4711")
        entry.minor_version = 1
        stubs.run(gp.async_migrate_entry(self.hass, entry))
        self.assertEqual(entry.data["account_id_source"], "profile_id")

    def test_current_entry_is_not_touched(self):
        entry = make_entry(source="profile_id", unique_id="4711")
        entry.minor_version = 2
        self.assertTrue(stubs.run(gp.async_migrate_entry(self.hass, entry)))
        self.assertEqual(self.hass.config_entries.updated, [])

    def test_newer_major_version_is_refused(self):
        entry = make_entry()
        entry.version = 2
        self.assertFalse(stubs.run(gp.async_migrate_entry(self.hass, entry)))

    def test_old_entry_end_to_end_migrate_then_setup(self):
        entry = make_entry(source=None)
        stubs.run(gp.async_migrate_entry(self.hass, entry))
        self.setup(entry)
        self.assertEqual((entry.unique_id, entry.data["account_id_source"]), ("4711", "profile_id"))
        self.assertEqual(entry.minor_version, 2)


class Remove(Base):
    def test_remove_deletes_issue_and_store_but_no_statistics(self):
        entry = make_entry(source="profile_id", unique_id="4711", days=2)
        self.setup(entry)
        self.assertIn((DOMAIN, "key_expiring_E1"), stubs.ISSUES)
        stubs.Store.instances.clear()
        stubs.run(gp.async_remove_entry(self.hass, entry))
        self.assertNotIn((DOMAIN, "key_expiring_E1"), stubs.ISSUES)
        self.assertEqual(len(stubs.Store.instances), 1)
        store = stubs.Store.instances[0]
        self.assertEqual(store.key, "garmin_personal.E1.activities")
        self.assertTrue(store.removed)
        self.assertEqual(stubs.RECORDED, [])  # imported statistics are kept


class DisabledSensorLog(Base):
    def test_disabled_sensors_are_logged_once_with_keys(self):
        entry = make_entry(source="profile_id", unique_id="4711")
        stubs.REGISTRY.entries["E1_steps"] = stubs.FakeRegistryEntry(None)
        orig = gp.sensors_to_prune
        gp.sensors_to_prune = lambda data: {"steps"}
        try:
            with self.assertLogs(gp._LOGGER, level="INFO") as logs:
                logging.disable(logging.NOTSET)
                coordinators = {n: SimpleNamespace(data={"x": 1}, last_update_success=True)
                                for n in ("daily", "sleep", "body", "activities", "profile")}
                entry.runtime_data = SimpleNamespace(coordinators=coordinators)
                gp._disable_empty_sensors_once(self.hass, entry)
        finally:
            gp.sensors_to_prune = orig
            logging.disable(logging.CRITICAL)
        self.assertTrue(any("steps" in line for line in logs.output))
        self.assertEqual(stubs.REGISTRY.updates[0][0], "sensor.E1_steps")


if __name__ == "__main__":
    unittest.main()
