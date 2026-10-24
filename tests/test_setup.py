"""__init__.py: _disable_empty_sensors_once, Optionen-Reload, Unload, Service-Registrierung."""

import logging
import sys
import unittest
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
        self.pruned_keys = {"steps", "distance"}
        gp.sensors_to_prune = lambda data: set(self.pruned_keys)
        self.addCleanup(lambda: setattr(gp, "sensors_to_prune", self.orig))

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
        gp.sensors_to_prune = lambda data: seen.update(data) or set()
        self.run_it(entry_with(dict(COMPLETE)))
        self.assertEqual(set(seen), set(COMPLETE))
        self.assertEqual(seen["body"], {"weight": []})

    def test_with_real_sensors_to_prune(self):
        gp.sensors_to_prune = self.orig
        coords = dict(COMPLETE, daily=coord({"summary": {"unrelated": 1}}))
        expected = self.orig({n: c.data for n, c in coords.items()})
        self.assertTrue(expected)  # Summary beantwortet, aber ohne bekannte Felder -> Sensoren leer
        register(*expected, "steps_not_pruned_marker")
        entry = entry_with(coords)
        self.run_it(entry)
        self.assertEqual({eid.split("_", 1)[1] for eid, _ in REG.updates}, expected)
        self.assertIsNone(REG.entries["E1_steps_not_pruned_marker"].disabled_by)


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
