"""History entities and backfill_history: ledger (append only), unsupported writer, entities (invented numbers)."""

import logging
import sys
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402
from intraday_fakes import hr_payload, ms  # noqa: E402

logging.disable(logging.CRITICAL)
gp = stubs.load_full()
sv = sys.modules["gp_full.services"]
hs = sys.modules["gp_full.history"]
sn = sys.modules["gp_full.sensor"]
api_mod = sys.modules["gp_full.api"]
DOMAIN = "garmin_personal"
NOW = datetime(2026, 10, 24, 12, 30, tzinfo=UTC)
D1, D2 = date(2026, 10, 23), date(2026, 10, 24)


class Entities(unittest.TestCase):
    def make(self):
        entry = stubs.FakeEntry(entry_id="E1", title="Alex")
        return [sn.GarminHistorySensor(entry, k, u) for k, u in sn.HISTORY_UNITS.items()]

    def test_disabled_diagnostic_and_without_live_value(self):
        for e in self.make():
            self.assertFalse(e._attr_entity_registry_enabled_default)
            self.assertEqual(e._attr_entity_category, sn.EntityCategory.DIAGNOSTIC)
            self.assertIsNone(e.native_value)
            self.assertIsNone(getattr(e, "_attr_state_class", None))

    def test_ids_units_and_keys(self):
        es = self.make()
        self.assertEqual([e._attr_unique_id for e in es], ["E1_heart_rate_history", "E1_body_battery_history", "E1_spo2_history"])
        self.assertEqual([e._attr_native_unit_of_measurement for e in es], ["bpm", "%", "%"])
        self.assertEqual(set(hs.HISTORY_KEYS.values()), set(sn.HISTORY_UNITS))


class LedgerTests(unittest.TestCase):
    P = [(1000, 60.0), (2000, 61.0), (3000, 62.0)]

    def test_new_then_same(self):
        led = hs.Ledger()
        self.assertFalse(led.knows("heart_rate", "2026-10-23"))
        new, same, changed = led.classify("heart_rate", "2026-10-23", self.P)
        self.assertEqual((new, same, changed), (self.P, 0, 0))
        led.record("heart_rate", "2026-10-23", new)
        self.assertEqual(led.classify("heart_rate", "2026-10-23", self.P), ([], 3, 0))

    def test_late_synced_older_point_is_new(self):
        led = hs.Ledger()
        led.record("heart_rate", "d", [(1000, 1.0), (3000, 3.0)])
        new, same, changed = led.classify("heart_rate", "d", [(1000, 1.0), (2000, 2.0), (3000, 3.0)])
        self.assertEqual((new, same, changed), ([(2000, 2.0)], 2, 0))  # older than the last written, never written

    def test_changed_value_is_counted_not_new(self):
        led = hs.Ledger()
        led.record("heart_rate", "d", [(1000, 1.0)])
        self.assertEqual(led.classify("heart_rate", "d", [(1000, 9.0)]), ([], 0, 1))
        led.record("heart_rate", "d", [(1000, 9.0)])  # recording never overwrites
        self.assertEqual(led.classify("heart_rate", "d", [(1000, 1.0)]), ([], 1, 0))

    def test_duplicates_in_input_count_once(self):
        led = hs.Ledger()
        self.assertEqual(led.classify("s", "d", [(5, 1.0), (5, 2.0)])[0], [(5, 1.0)])

    def test_series_and_days_are_separate(self):
        led = hs.Ledger()
        led.record("heart_rate", "d1", [(1, 1.0)])
        self.assertEqual(led.classify("heart_rate", "d2", [(1, 1.0)])[0], [(1, 1.0)])
        self.assertEqual(led.classify("spo2", "d1", [(1, 1.0)])[0], [(1, 1.0)])

    def test_old_days_shrink_to_a_mark_and_keep_working(self):
        led = hs.Ledger()
        led.record("heart_rate", "2026-10-01", self.P)
        led.record("heart_rate", "2026-10-23", self.P)
        led.compact("2026-10-24")
        old = led.data["series"]["heart_rate"]["2026-10-01"]
        self.assertEqual((old["n"], old["lo"], old["hi"]), (3, 1000, 3000))
        self.assertIn("p", led.data["series"]["heart_rate"]["2026-10-23"])  # recent day keeps details
        self.assertEqual(led.classify("heart_rate", "2026-10-01", self.P), ([], 3, 0))
        new, _, _ = led.classify("heart_rate", "2026-10-01", [(5000, 5.0)])
        self.assertEqual(new, [(5000, 5.0)])
        led.record("heart_rate", "2026-10-01", new)
        self.assertEqual(led.data["series"]["heart_rate"]["2026-10-01"]["n"], 4)

    def test_mark_checksum_is_order_independent(self):
        a, b = hs.Ledger(), hs.Ledger()
        a.record("s", "2026-10-01", self.P)
        b.record("s", "2026-10-01", list(reversed(self.P)))
        a.compact("2026-10-24")
        b.compact("2026-10-24")
        self.assertEqual(a.data, b.data)

    def test_bad_stored_data_gives_a_fresh_ledger(self):
        for bad in (None, {}, {"v": 99, "series": {}}, {"v": 1, "series": 5}, "x"):
            self.assertEqual(hs.Ledger(bad).data, {"v": 1, "series": {}})

    def test_new_points_helper(self):
        self.assertEqual(hs.new_points([(3, 1.0), (1, 2.0), (1, 9.0)], None), [(1, 2.0), (3, 1.0)])
        self.assertEqual(hs.new_points([(3, 1.0), (1, 2.0)], 1), [(3, 1.0)])


class FakeApi:
    def __init__(self):
        self.hr = {}
        self.calls = 0

    async def get_heart_rate(self, day):
        self.calls += 1
        return self.hr.get(day)

    async def get_body_battery(self, a, b):
        self.calls += 1

    async def get_spo2(self, day):
        self.calls += 1


class ServiceTests(unittest.TestCase):
    def setUp(self):
        stubs.Store.instances.clear()
        stubs.Store.preset = None
        self.api = FakeApi()
        self.entry = stubs.FakeEntry(entry_id="E1", title="Alex", runtime_data=type("R", (), {"api": self.api})())
        self.hass = stubs.FakeHass()
        self.hass.config_entries.entries = [self.entry]
        sv.async_register_services(self.hass)
        self.written = []
        self.recorded = {}  # (series, day) -> {ts: value}; missing key: recorder cannot be asked

        async def writer(hass, entry, series, points):
            self.written.append((series, list(points)))
            return len(points), None

        async def reader(hass, entry, series, day):
            if (series, day) not in self.recorded:
                raise hs.HistoryWriteUnsupported("no")
            return self.recorded[(series, day)]

        async def target(hass, entry, series):
            return f"sensor.alex_{series}_history"

        self.patch(sv, "check_target", target)
        self.patch(hs, "check_target", target)
        self.patch(hs, "write_history_states", writer)
        self.patch(hs, "recorded_points", reader)
        for name in ("now", "utcnow"):
            self.patch(sv.dt_util, name, lambda: NOW)

    def patch(self, obj, name, value):
        orig = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, orig)

    def call(self, data=None):
        handler = self.hass.services.registered[(DOMAIN, "backfill_history")]["handler"]
        return stubs.run(handler(stubs.FakeCall({"series": ["heart_rate"], **(data or {})})))

    def feed(self, day, rows):
        self.api.hr[day] = hr_payload(rows)

    def test_limits(self):
        with self.assertRaises(stubs.ServiceValidationError) as ctx:
            self.call({"days": 32})
        self.assertEqual(ctx.exception.translation_key, "date_range_too_long")
        self.assertEqual(ctx.exception.translation_placeholders["max_days"], "31")
        self.assertEqual(self.api.calls, 0)

    def test_several_series_and_default_all(self):
        self.recorded[("heart_rate", D2)] = {}
        self.feed(D2, [(ms(2026, 10, 24, 8, 0), 60)])
        self.call({"series": ["heart_rate", "spo2", "body_battery"]})
        self.assertEqual(self.api.calls, 3)
        self.api.calls = 0
        self.call({"series": None})
        self.assertEqual(self.api.calls, 3)

    def test_target_problem_stops_before_any_request(self):
        async def missing(hass, entry, series):
            raise hs.HistoryTargetError("history_sensor_disabled", "sensor.x")

        self.patch(sv, "check_target", missing)
        with self.assertRaises(stubs.ServiceValidationError) as ctx:
            self.call()
        self.assertEqual(ctx.exception.translation_key, "history_sensor_disabled")
        self.assertEqual(ctx.exception.translation_placeholders["entity_id"], "sensor.x")
        self.assertEqual(self.api.calls, 0)

    def test_partial_write_notes_only_what_was_handed_over(self):
        t = [ms(2026, 10, 24, 8, m) for m in (0, 2, 4)]
        self.recorded[("heart_rate", D2)] = {}
        self.feed(D2, [(x, 60 + i) for i, x in enumerate(t)])

        async def flaky(hass, entry, series, points):
            return 2, "boom"

        self.patch(hs, "write_history_states", flaky)
        out = self.call()
        self.assertIs(out["complete"], False)
        self.assertEqual((out["points_written"], out["error"]), (2, "history_write_failed: boom"))
        saved = stubs.Store.instances[-1].saved[-1]["series"]["heart_rate"]["2026-10-24"]["p"]
        self.assertEqual(sorted(saved), [str(t[0]), str(t[1])])  # the third point stays open

    def test_writes_points_oldest_first_with_real_timestamps_and_drops_placeholders(self):
        t1, t2, t3 = ms(2026, 10, 24, 8, 4), ms(2026, 10, 24, 8, 0), ms(2026, 10, 24, 8, 2)
        self.feed(D2, [(t1, 70), (t2, 60), (t3, 0)])
        self.recorded[("heart_rate", D2)] = {}
        out = self.call({"days": 1})
        self.assertEqual(self.written, [("heart_rate", [(t2, 60.0), (t1, 70.0)])])
        self.assertEqual((out["points_written"], out["changed_values_skipped"], out["complete"]), (2, 0, True))

    def test_repeat_writes_nothing_twice(self):
        t = ms(2026, 10, 24, 8, 0)
        self.feed(D2, [(t, 60)])
        self.recorded[("heart_rate", D2)] = {}
        self.call()
        stubs.Store.preset = stubs.Store.instances[-1].saved[-1]  # what the store holds now
        out = self.call()
        self.assertEqual(len(self.written), 1)
        self.assertEqual((out["points_written"], out["points_already_written"]), (0, 1))

    def test_late_synced_point_is_added_later(self):
        t1, t2, t3 = (ms(2026, 10, 24, 8, m) for m in (0, 2, 4))
        self.recorded[("heart_rate", D2)] = {}
        self.feed(D2, [(t1, 60), (t3, 64)])
        self.call()
        stubs.Store.preset = stubs.Store.instances[-1].saved[-1]
        self.feed(D2, [(t1, 60), (t2, 62), (t3, 64)])
        out = self.call()
        self.assertEqual(self.written[-1], ("heart_rate", [(t2, 62.0)]))
        self.assertEqual(out["points_written"], 1)

    def test_changed_value_is_not_rewritten_but_counted(self):
        t = ms(2026, 10, 24, 8, 0)
        self.recorded[("heart_rate", D2)] = {}
        self.feed(D2, [(t, 60)])
        self.call()
        stubs.Store.preset = stubs.Store.instances[-1].saved[-1]
        self.feed(D2, [(t, 99)])
        out = self.call()
        self.assertEqual(len(self.written), 1)
        self.assertEqual((out["points_written"], out["changed_values_skipped"]), (0, 1))

    def test_lost_ledger_adopts_what_the_recorder_has(self):
        t1, t2 = ms(2026, 10, 24, 8, 0), ms(2026, 10, 24, 8, 2)
        self.recorded[("heart_rate", D2)] = {t1: 60.0}
        self.feed(D2, [(t1, 60), (t2, 62)])
        out = self.call()
        self.assertEqual(self.written, [("heart_rate", [(t2, 62.0)])])
        self.assertEqual((out["points_found_in_recorder"], out["points_already_written"]), (1, 1))

    def test_lost_ledger_and_no_recorder_check_writes_nothing_without_confirmation(self):
        self.feed(D2, [(ms(2026, 10, 24, 8, 0), 60)])
        out = self.call()
        self.assertEqual((self.written, out["days_skipped_unverified"], out["points_written"]), ([], 1, 0))

    def test_confirm_rewrite_writes_the_unverifiable_day(self):
        self.feed(D2, [(ms(2026, 10, 24, 8, 0), 60)])
        out = self.call({"confirm_rewrite": True})
        self.assertEqual(out["points_written"], 1)

    def test_day_change_keeps_days_apart(self):
        a, b = ms(2026, 10, 23, 23, 58), ms(2026, 10, 24, 0, 2)
        self.recorded[("heart_rate", D1)] = {}
        self.recorded[("heart_rate", D2)] = {}
        self.feed(D1, [(a, 60)])
        self.feed(D2, [(b, 61)])
        out = self.call({"days": 2})
        self.assertEqual([w[1] for w in self.written], [[(a, 60.0)], [(b, 61.0)]])
        self.assertEqual(out["days_completed"], 2)
        stubs.Store.preset = stubs.Store.instances[-1].saved[-1]
        again = self.call({"days": 2})
        self.assertEqual(again["points_written"], 0)

    def test_rate_limit_stops_with_partial_result(self):
        self.recorded[("heart_rate", D1)] = {}
        self.feed(D1, [(ms(2026, 10, 23, 8, 0), 60)])

        async def limited(day):
            if day == D2:
                raise api_mod.GarminRateLimitError("429")
            return self.api.hr.get(day)

        self.api.get_heart_rate = limited
        out = self.call({"days": 2})
        self.assertIs(out["complete"], False)
        self.assertEqual(out["last_completed_day"], "2026-10-23")
        self.assertEqual(out["points_written"], 1)


if __name__ == "__main__":
    unittest.main()
