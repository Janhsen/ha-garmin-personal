"""__init__.py: _disable_empty_sensors_once, Optionen-Reload, Unload, Service-Registrierung."""

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
DOMAIN = "garmin_personal"
REG = stubs.REGISTRY


def coord(data, ok=True):
    return SimpleNamespace(data=data, last_update_success=ok)


def entry_with(coordinators, pruned=False, options=None):
    runtime = SimpleNamespace(coordinators=coordinators, options=dict(options or {}))
    data = {"api_key": "K"}
    if pruned:
        data[const.CONF_PRUNED] = True
    return stubs.FakeEntry(entry_id="E1", data=data, options=options, runtime_data=runtime)


def register(*keys, disabled_by=None):
    for key in keys:
        REG.entries[f"E1_{key}"] = stubs.FakeRegistryEntry(disabled_by)


COMPLETE = {"daily": coord({"summary": {"x": 1}}), "sleep": coord({"sleep": {"a": 1}}),
            "body": coord({"weight": []}), "activities": coord({"activities": []}),
            "profile": coord({"profile": {"a": 1}})}


class DisableOnce(unittest.TestCase):
    def setUp(self):
        REG.entries.clear()
        REG.updates.clear()
        self.hass = stubs.FakeHass()
        self.orig = gp.sensors_to_prune
        self.orig_blocker = gp.prune_blocker
        self.pruned_keys = {"steps", "distance"}
        gp.sensors_to_prune = lambda data, created=None: set(self.pruned_keys)
        gp.prune_blocker = lambda data, created, now=None: None
        self.addCleanup(lambda: setattr(gp, "sensors_to_prune", self.orig))
        self.addCleanup(lambda: setattr(gp, "prune_blocker", self.orig_blocker))

    def run_it(self, entry):
        gp._disable_empty_sensors_once(self.hass, entry)

    def test_already_pruned_does_nothing(self):
        register("steps", "distance")
        entry = entry_with(dict(COMPLETE), pruned=True)
        self.run_it(entry)
        self.assertEqual(REG.updates, [])
        self.assertEqual(self.hass.config_entries.updated, [])

    def test_incomplete_failed_group_does_nothing_and_flag_stays_unset(self):
        register("steps", "distance")
        coords = dict(COMPLETE, sleep=coord({"sleep": {"a": 1}}, ok=False))
        entry = entry_with(coords)
        self.run_it(entry)
        self.assertEqual(REG.updates, [])
        self.assertEqual(self.hass.config_entries.updated, [])
        self.assertNotIn(const.CONF_PRUNED, entry.data)

    def test_incomplete_empty_data_does_nothing(self):
        register("steps")
        for empty in (None, {}):
            entry = entry_with(dict(COMPLETE, body=coord(empty)))
            self.run_it(entry)
            self.assertEqual(REG.updates, [])
            self.assertNotIn(const.CONF_PRUNED, entry.data)

    def test_complete_disables_and_sets_flag(self):
        register("steps", "distance", "other")
        entry = entry_with(dict(COMPLETE))
        self.run_it(entry)
        disabled = {eid for eid, kw in REG.updates}
        self.assertEqual(disabled, {"sensor.E1_steps", "sensor.E1_distance"})
        for _, kw in REG.updates:
            self.assertEqual(kw, {"disabled_by": stubs.RegistryEntryDisabler.INTEGRATION})
        self.assertIsNone(REG.entries["E1_other"].disabled_by)  # nicht in der Prune-Liste
        self.assertIs(entry.data[const.CONF_PRUNED], True)
        self.assertEqual(entry.data["api_key"], "K")  # übrige Daten bleiben
        self.assertEqual(len(self.hass.config_entries.updated), 1)

    def test_already_disabled_not_touched(self):
        register("steps", disabled_by=stubs.RegistryEntryDisabler.USER)
        register("distance", disabled_by=stubs.RegistryEntryDisabler.INTEGRATION)
        self.run_it(entry_with(dict(COMPLETE)))
        self.assertEqual(REG.updates, [])
        self.assertIs(REG.entries["E1_steps"].disabled_by, stubs.RegistryEntryDisabler.USER)

    def test_missing_registry_entries_skipped(self):
        register("steps")  # "distance" ist nicht registriert
        entry = entry_with(dict(COMPLETE))
        self.run_it(entry)
        self.assertEqual([eid for eid, _ in REG.updates], ["sensor.E1_steps"])
        self.assertIs(entry.data[const.CONF_PRUNED], True)

    def test_flag_set_even_if_nothing_to_prune(self):
        self.pruned_keys = set()
        entry = entry_with(dict(COMPLETE))
        self.run_it(entry)
        self.assertIs(entry.data[const.CONF_PRUNED], True)

    def test_runs_only_once(self):
        register("steps", "distance")
        entry = entry_with(dict(COMPLETE))
        self.run_it(entry)
        n_updates = len(REG.updates)
        # Nutzer aktiviert einen Sensor wieder -> zweiter Start darf ihn nicht erneut deaktivieren
        REG.entries["E1_steps"].disabled_by = None
        self.run_it(entry)
        self.assertEqual(len(REG.updates), n_updates)
        self.assertIsNone(REG.entries["E1_steps"].disabled_by)
        self.assertEqual(len(self.hass.config_entries.updated), 1)

    def test_prune_input_is_data_by_group_name(self):
        seen = {}
        gp.sensors_to_prune = lambda data, created=None: seen.update(data) or set()
        self.run_it(entry_with(dict(COMPLETE)))
        self.assertEqual(set(seen), set(COMPLETE))
        self.assertEqual(seen["body"], {"weight": []})

    def real_coordinators(self):
        synced = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.0")
        weighing = {"dailyWeightSummaries": [{"summaryDate": "2026-10-20",
                                              "latestWeight": {"weight": 80000, "sourceType": "MANUAL"}}]}
        return dict(COMPLETE, daily=coord({"summary": {"totalSteps": 5, "lastSyncTimestampGMT": synced}}),
                    body=coord({"weight": weighing}))

    def test_real_decision_uses_the_age_of_the_entry_and_marks_done(self):
        gp.sensors_to_prune, gp.prune_blocker = self.orig, self.orig_blocker
        register("bmi", "last_activity_avg_hr")
        entry = entry_with(self.real_coordinators())
        self.run_it(entry)
        self.assertEqual([eid for eid, _ in REG.updates], ["sensor.E1_bmi"])  # empty body value, answered endpoint
        self.assertIsNone(REG.entries["E1_last_activity_avg_hr"].disabled_by)  # activity sensors are never pruned
        self.assertIs(entry.data[const.CONF_PRUNED], True)

    def test_too_young_or_unknown_age_does_not_mark_the_pruning_as_done(self):
        gp.sensors_to_prune, gp.prune_blocker = self.orig, self.orig_blocker
        register("bmi")
        for created in (datetime.now(UTC) - timedelta(hours=1), None):
            entry = entry_with(self.real_coordinators())
            entry.created_at = created
            self.run_it(entry)
            self.assertEqual(REG.updates, [])
            self.assertNotIn(const.CONF_PRUNED, entry.data)  # it is tried again at the next start
            self.assertEqual(self.hass.config_entries.updated, [])

    def test_blocker_is_checked_before_anything_is_changed(self):
        gp.prune_blocker = lambda data, created, now=None: "the watch has not synchronised today"
        register("steps")
        entry = entry_with(dict(COMPLETE))
        self.run_it(entry)
        self.assertEqual(REG.updates, [])
        self.assertNotIn(const.CONF_PRUNED, entry.data)


class RetryFailedGroups(unittest.TestCase):
    def setUp(self):
        stubs.LATER.clear()
        self.hass = stubs.FakeHass()

    def make(self, failing):
        refreshed = []

        def group(name):
            async def refresh():
                refreshed.append(name)
                c.last_update_success = True

            c = SimpleNamespace(data={"x": 1}, last_update_success=name not in failing, async_refresh=refresh)
            return c

        names = ("daily", "sleep", "body", "activities", "profile")
        entry = entry_with({n: group(n) for n in names})
        return entry, refreshed

    def test_nothing_failed_nothing_scheduled(self):
        entry, _ = self.make(())
        gp._retry_failed_groups(self.hass, entry)
        self.assertEqual(stubs.LATER, [])

    def test_failed_secondary_group_is_asked_again_soon_but_not_the_daily_one(self):
        entry, refreshed = self.make(("profile", "daily"))
        gp._retry_failed_groups(self.hass, entry)
        self.assertEqual([t["delay"] for t in stubs.LATER], [300])
        self.assertEqual(len(entry.unload_callbacks), 1)  # cancelled with the entry
        stubs.run(stubs.LATER[0]["action"](None))
        self.assertEqual(refreshed, ["profile"])
        self.assertEqual(len(stubs.LATER), 1)  # it worked: no further retry

    def test_gives_up_after_three_attempts(self):
        entry, refreshed = self.make(("profile",))
        coordinator = entry.runtime_data.coordinators["profile"]

        async def still_failing():
            refreshed.append("profile")

        coordinator.async_refresh = still_failing
        gp._retry_failed_groups(self.hass, entry)
        for _ in range(5):
            if stubs.LATER and not stubs.LATER[-1].get("done"):
                stubs.LATER[-1]["done"] = True
                stubs.run(stubs.LATER[-1]["action"](None))
        self.assertEqual(len(stubs.LATER), 3)
        self.assertEqual(refreshed, ["profile"] * 3)


class Unload(unittest.TestCase):
    def make(self):
        calls = []

        async def stop_jobs():
            calls.append("jobs")

        async def stop_history():
            calls.append("history")

        runtime = SimpleNamespace(
            coordinators={"daily": SimpleNamespace(async_stop_jobs=stop_jobs)},
            history=SimpleNamespace(async_stop=stop_history),
        )
        return stubs.FakeEntry(entry_id="E1", runtime_data=runtime), calls

    def test_background_jobs_are_stopped_and_awaited_after_the_platforms_unload(self):
        hass = stubs.FakeHass()
        entry, calls = self.make()
        self.assertTrue(stubs.run(gp.async_unload_entry(hass, entry)))
        self.assertEqual(calls, ["jobs", "history"])

    def test_nothing_is_stopped_if_the_platforms_stay(self):
        hass = stubs.FakeHass()

        async def refuse(entry, platforms):
            return False

        hass.config_entries.async_unload_platforms = refuse
        entry, calls = self.make()
        self.assertFalse(stubs.run(gp.async_unload_entry(hass, entry)))
        self.assertEqual(calls, [])

    def test_entry_without_a_history_manager_unloads(self):
        entry = stubs.FakeEntry(entry_id="E1", runtime_data=SimpleNamespace(coordinators={}, history=None))
        self.assertTrue(stubs.run(gp.async_unload_entry(stubs.FakeHass(), entry)))


class Misc(unittest.TestCase):
    def test_async_setup_registers_services(self):
        hass = stubs.FakeHass()
        self.assertTrue(stubs.run(gp.async_setup(hass, {})))
        self.assertTrue(hass.services.has_service(DOMAIN, "fetch"))

    def test_no_update_listener_is_left_behind(self):
        """Options reload through OptionsFlowWithReload; a listener would double the reload."""
        self.assertFalse(hasattr(gp, "_async_reload_on_options"))

    def test_platforms(self):
        self.assertEqual([p.value for p in gp.PLATFORMS], ["sensor", "binary_sensor", "calendar", "event"])


if __name__ == "__main__":
    unittest.main()
