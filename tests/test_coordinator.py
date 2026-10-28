"""coordinator.py: Basis-Koordinator (Fehler, Sticky, 429, Auth) und GarminActivityCoordinator."""

import logging
import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402

logging.disable(logging.CRITICAL)
gp = stubs.load_full()
co = sys.modules["gp_full.coordinator"]
api_mod = sys.modules["gp_full.api"]


def ok(value):
    async def call():
        return value
    return call


def boom(exc):
    async def call():
        raise exc
    return call


def counting(value=None, exc=None):
    async def call():
        call.n += 1
        if exc:
            raise exc
        return value
    call.n = 0
    return call


class Calls:
    """Wechselnder Satz an Aufrufen pro Zyklus."""

    def __init__(self, *cycles):
        self.cycles = list(cycles)

    def __call__(self, api, today):
        return self.cycles.pop(0) if len(self.cycles) > 1 else self.cycles[0]


def make(cls, calls, sticky=(), group="g"):
    entry = stubs.FakeEntry(entry_id="E1", title="Alex")
    return cls(stubs.FakeHass(), entry, object(), group, timedelta(minutes=5), calls, sticky=sticky)


def update(c):
    return stubs.run(c._async_update_data())


def refresh(c):
    stubs.run(c.async_refresh())
    return c.data


class BaseCoordinator(unittest.TestCase):
    def test_collects_results_and_day(self):
        c = make(co.GarminCoordinator, Calls({"a": ok(1), "b": ok({"x": 2})}))
        data = update(c)
        self.assertEqual((data["a"], data["b"]), (1, {"x": 2}))
        self.assertRegex(data["_day"], r"^\d{4}-\d{2}-\d{2}$")

    def test_one_failing_endpoint_only_empties_itself(self):
        c = make(co.GarminCoordinator, Calls({"a": ok(1), "b": boom(api_mod.GarminApiError("x", 500))}))
        data = update(c)
        self.assertEqual((data["a"], data["b"]), (1, None))

    def test_all_failing_raises_update_failed(self):
        c = make(co.GarminCoordinator, Calls({"a": boom(api_mod.GarminApiError("e1")),
                                              "b": boom(api_mod.GarminApiError("e2"))}))
        with self.assertRaisesRegex(stubs.UpdateFailed, "a: e1; b: e2"):
            update(c)

    def test_update_failed_marks_refresh_unsuccessful(self):
        c = make(co.GarminCoordinator, Calls({"a": boom(api_mod.GarminApiError("e"))}))
        refresh(c)
        self.assertFalse(c.last_update_success)

    def test_rate_limit_aborts_cycle(self):
        later = counting(1)
        c = make(co.GarminCoordinator, Calls({"a": ok(1), "b": boom(api_mod.GarminRateLimitError("429")),
                                             "c": later}))
        with self.assertRaisesRegex(stubs.UpdateFailed, "429"):
            update(c)
        self.assertEqual(later.n, 0)  # restliche Endpunkte werden nicht mehr angefragt

    def test_rate_limit_keeps_previous_data_via_failed_refresh(self):
        c = make(co.GarminCoordinator, Calls({"a": ok(1)}, {"a": boom(api_mod.GarminRateLimitError("429"))}))
        refresh(c)
        self.assertEqual(c.data["a"], 1)
        refresh(c)
        # Ein einzelner Fehlzyklus hält die Daten (Entities bleiben verfügbar), siehe test_conn_*.py
        self.assertTrue(c.last_update_success)
        self.assertEqual(c.data["a"], 1)

    def test_auth_error_becomes_config_entry_auth_failed(self):
        later = counting(1)
        c = make(co.GarminCoordinator, Calls({"a": boom(api_mod.GarminAuthError("expired")), "b": later}))
        with self.assertRaises(stubs.ConfigEntryAuthFailed) as ctx:
            update(c)
        self.assertIn("expired", str(ctx.exception))
        self.assertEqual(later.n, 0)

    def test_auth_error_in_later_endpoint_also_raises(self):
        c = make(co.GarminCoordinator, Calls({"a": ok(1), "b": boom(api_mod.GarminAuthError("x"))}))
        with self.assertRaises(stubs.ConfigEntryAuthFailed):
            update(c)

    def test_auth_error_not_swallowed_by_refresh(self):
        c = make(co.GarminCoordinator, Calls({"a": boom(api_mod.GarminAuthError("x"))}))
        with self.assertRaises(stubs.ConfigEntryAuthFailed):
            refresh(c)

    def test_warning_logged_once_per_endpoint_and_reset_on_success(self):
        c = make(co.GarminCoordinator, Calls({"a": ok(1), "b": boom(api_mod.GarminApiError("x"))},
                                             {"a": ok(1), "b": boom(api_mod.GarminApiError("x"))},
                                             {"a": ok(1), "b": ok(2)}))
        update(c)
        self.assertEqual(c._warned, {"b"})
        update(c)
        self.assertEqual(c._warned, {"b"})
        update(c)
        self.assertEqual(c._warned, set())

    def test_sleep_is_unwrapped(self):
        c = make(co.GarminCoordinator, Calls({"sleep": ok({"dailySleepDTO": {"sleepTimeSeconds": 100}, "z": 1})}))
        data = update(c)
        self.assertEqual(data["sleep"]["sleepTimeSeconds"], 100)
        self.assertEqual(data["sleep"]["z"], 1)

    def test_unwrap_sleep_passthrough(self):
        self.assertIsNone(co.unwrap_sleep(None))
        self.assertEqual(co.unwrap_sleep({"a": 1}), {"a": 1})
        self.assertEqual(co.unwrap_sleep({"dailySleepDTO": None}), {"dailySleepDTO": None})


class Sticky(unittest.TestCase):
    def test_keeps_last_good_value_for_empty_results(self):
        for empty in (None, [], {}, {"a": None, "b": None}):
            c = make(co.GarminCoordinator, Calls({"sleep": ok({"v": 1}), "other": ok(5)},
                                                 {"sleep": ok(empty), "other": ok(None)}),
                     sticky=("sleep",))
            refresh(c)
            data = refresh(c)
            self.assertEqual(data["sleep"], {"v": 1}, empty)
            self.assertIsNone(data["other"])  # nicht sticky

    def test_sticky_applies_when_endpoint_fails(self):
        c = make(co.GarminCoordinator, Calls({"a": ok(1), "w": ok([{"x": 1}])},
                                             {"a": ok(2), "w": boom(api_mod.GarminApiError("x"))}),
                 sticky=("w",))
        refresh(c)
        self.assertEqual(refresh(c)["w"], [{"x": 1}])

    def test_new_value_replaces_sticky(self):
        c = make(co.GarminCoordinator, Calls({"sleep": ok({"v": 1})}, {"sleep": ok({"v": 2})}),
                 sticky=("sleep",))
        refresh(c)
        self.assertEqual(refresh(c)["sleep"], {"v": 2})

    def test_empty_stays_empty_when_nothing_before(self):
        c = make(co.GarminCoordinator, Calls({"sleep": ok(None), "o": ok(1)}), sticky=("sleep",))
        self.assertIsNone(update(c)["sleep"])

    def test_zero_is_not_empty(self):
        c = make(co.GarminCoordinator, Calls({"w": ok([1])}, {"w": ok(0)}), sticky=("w",))
        refresh(c)
        self.assertEqual(refresh(c)["w"], 0)


def act(i):
    return {"activityId": i, "activityName": f"A{i}"}


class ActivityCoordinator(unittest.TestCase):
    def setUp(self):
        stubs.Store.instances.clear()
        stubs.Store.preset = None

    def make(self, *cycles, sticky=("activities",)):
        calls = Calls(*({"activities": ok(a), "wellness_activities": ok([])} for a in cycles))
        return make(co.GarminActivityCoordinator, calls, sticky=sticky, group="activities")

    def store(self):
        return stubs.Store.instances[-1]

    def test_store_key(self):
        c = self.make([act(1)])
        self.assertEqual(self.store().key, "garmin_personal.E1.activities")

    def test_first_run_reports_nothing_new_but_stores_newest(self):
        c = self.make([act(5), act(9), act(7)])
        data = update(c)
        self.assertEqual(data["new_activities"], [])
        self.assertEqual(self.store().saved, [{"last_id": 9}])
        self.assertEqual(c._last_id, 9)

    def test_later_run_reports_only_newer_ids_sorted(self):
        c = self.make([act(5), act(9)], [act(12), act(9), act(5), act(10)])
        update(c)
        data = update(c)
        self.assertEqual([a["activityId"] for a in data["new_activities"]], [10, 12])
        self.assertEqual(self.store().saved, [{"last_id": 9}, {"last_id": 12}])

    def test_nothing_new_and_no_extra_save(self):
        c = self.make([act(5)], [act(5)])
        update(c)
        data = update(c)
        self.assertEqual(data["new_activities"], [])
        self.assertEqual(len(self.store().saved), 1)

    def test_new_activities_not_repeated_in_following_cycle(self):
        c = self.make([act(5)], [act(6), act(5)], [act(6), act(5)])
        update(c)
        self.assertEqual(len(update(c)["new_activities"]), 1)
        self.assertEqual(update(c)["new_activities"], [])

    def test_stored_last_id_is_used_after_restart(self):
        stubs.Store.preset = {"last_id": 5}
        c = self.make([act(7), act(5), act(6)])
        data = update(c)
        self.assertEqual([a["activityId"] for a in data["new_activities"]], [6, 7])
        self.assertEqual(self.store().saved, [{"last_id": 7}])

    def test_store_loaded_only_once(self):
        loads = []
        orig = stubs.Store.async_load

        async def counting_load(self):
            loads.append(1)
            return await orig(self)

        stubs.Store.async_load = counting_load
        try:
            c = self.make([act(1)], [act(2)], [act(3)])
            for _ in range(3):
                update(c)
        finally:
            stubs.Store.async_load = orig
        self.assertEqual(len(loads), 1)

    def test_older_newest_id_does_not_lower_last_id(self):
        c = self.make([act(9)], [act(4)])  # z. B. neueste Aktivität gelöscht
        update(c)
        data = update(c)
        self.assertEqual(data["new_activities"], [])
        self.assertEqual(c._last_id, 9)
        self.assertEqual(len(self.store().saved), 1)

    def test_junk_entries_ignored(self):
        c = self.make([act(5)], ["x", None, {"activityId": "9"}, {"activityId": None}, {"name": "n"}, act(6)])
        update(c)
        data = update(c)
        self.assertEqual([a["activityId"] for a in data["new_activities"]], [6])

    def test_failed_activity_endpoint_with_sticky_reports_nothing(self):
        calls = Calls({"activities": ok([act(5)])}, {"activities": boom(api_mod.GarminApiError("x"))},
                      {"activities": boom(api_mod.GarminApiError("x"))})
        c = make(co.GarminActivityCoordinator, calls, sticky=("activities",))
        update(c)
        # alle Endpunkte schlagen fehl -> UpdateFailed; Store bleibt unberührt
        with self.assertRaises(stubs.UpdateFailed):
            update(c)
        self.assertEqual(len(self.store().saved), 1)

    def test_partial_failure_uses_sticky_list_without_new(self):
        calls = Calls({"activities": ok([act(5)]), "w": ok(1)},
                      {"activities": boom(api_mod.GarminApiError("x")), "w": ok(2)})
        c = make(co.GarminActivityCoordinator, calls, sticky=("activities",))
        refresh(c)  # refresh() setzt c.data, das der nächste Zyklus als "previous" nutzt
        data = refresh(c)
        self.assertEqual(data["activities"], [act(5)])
        self.assertEqual(data["new_activities"], [])

    def test_rate_limit_and_auth_propagate(self):
        c = make(co.GarminActivityCoordinator, Calls({"activities": boom(api_mod.GarminRateLimitError("429"))}),
                 sticky=("activities",))
        with self.assertRaises(stubs.UpdateFailed):
            update(c)
        c = make(co.GarminActivityCoordinator, Calls({"activities": boom(api_mod.GarminAuthError("k"))}),
                 sticky=("activities",))
        with self.assertRaises(stubs.ConfigEntryAuthFailed):
            update(c)
        self.assertEqual(self.store().saved, [])

    def test_empty_first_answer_sets_no_baseline(self):
        # An empty first answer may be a hiccup; the next full list must not become 20 events.
        # (Trade-off: the very first activity of a brand-new account is not reported.)
        c = self.make([], [act(1), act(2)])
        update(c)
        data = update(c)
        self.assertEqual(data["new_activities"], [])


class ProfileCoordinator(unittest.TestCase):
    def test_updates_expiry_issue_each_cycle(self):
        calls_seen = []
        orig = co.update_key_expiry_issue
        co.update_key_expiry_issue = lambda hass, entry: calls_seen.append(entry.entry_id)
        try:
            c = make(co.GarminProfileCoordinator, Calls({"profile": ok({"a": 1})}), sticky=("profile",))
            update(c)
            update(c)
        finally:
            co.update_key_expiry_issue = orig
        self.assertEqual(calls_seen, ["E1", "E1"])


if __name__ == "__main__":
    unittest.main()
