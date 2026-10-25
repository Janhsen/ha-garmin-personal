"""Body Battery every 3 minutes (chunks=288, 0.5.9): parser, request, ledger reload (invented numbers in Garmin's format)."""

import logging
import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402
import test_history_auto as tha  # noqa: E402
from intraday_fakes import bb_payload, ms  # noqa: E402

logging.disable(logging.CRITICAL)
iv = sys.modules["gp_full.intraday"]
hs = sys.modules["gp_full.history"]
sn = sys.modules["gp_full.sensor"]
D = tha.D
T0 = ms(2026, 10, 22, 6, 0)
STEP = 180_000


def dense_payload(n=40, placeholders=8):
    """Like the live answer with chunks=288: repeated timestamps at interval borders, then null rows +1 ms each."""
    rows = []
    for i in range(n):
        rows.append((T0 + i * STEP, 50 + i % 7))
        if i % 5 == 4:
            rows.append((T0 + i * STEP, 50 + i % 7))  # same timestamp, same value
    last = T0 + n * STEP
    rows.extend((last + k, None) for k in range(placeholders))
    return bb_payload(rows)


class Parser(unittest.TestCase):
    def test_nulls_and_duplicates_are_dropped_no_real_point_is_lost(self):
        points = iv.body_battery_points(dense_payload())
        self.assertEqual(len(points), 40)
        self.assertEqual(points[0], (T0, 50.0))
        self.assertEqual([ts for ts, _ in points], [T0 + i * STEP for i in range(40)])
        self.assertEqual(points, sorted(set(points)))

    def test_zero_is_a_real_level_and_point_type_is_unchanged(self):
        points = iv.body_battery_points(bb_payload([(T0, 0), (T0, 0), (T0 + STEP, None)]))
        self.assertEqual(points, [(T0, 0.0)])
        self.assertIsInstance(points[0], tuple)

    def test_two_days_overlapping_count_once(self):
        a, b = bb_payload([(T0, 80), (T0 + STEP, 79)])[0], bb_payload([(T0 + STEP, 79), (T0 + 2 * STEP, 78)])[0]
        self.assertEqual(iv.body_battery_points([a, b]), [(T0, 80.0), (T0 + STEP, 79.0), (T0 + 2 * STEP, 78.0)])

    def test_hourly_mean_is_not_skewed_by_duplicates(self):
        hours = iv.hourly_aggregate(iv.body_battery_points(bb_payload([(T0, 10), (T0, 10), (T0 + STEP, 20)])))
        stat = next(iter(hours.values()))
        self.assertEqual((stat.minimum, stat.maximum, stat.mean, stat.count), (10.0, 20.0, 15.0, 2))

    def test_sensor_attribute_has_no_duplicates_or_nulls(self):
        values = sn._body_battery_intraday({"body_battery": dense_payload()})["values"]
        self.assertEqual(len(values), 40)


class Request(unittest.TestCase):
    def test_series_job_asks_with_chunks_288(self):
        seen = []

        class Api:
            async def get_body_battery(self, a, b, chunks=None):
                seen.append((a, b, chunks))

        stubs.run(iv.fetch_series(Api(), "body_battery", D))
        self.assertEqual(seen, [(D, D, 288)])

    def test_daily_call_shares_the_same_request(self):
        co = sys.modules["gp_full.coordinator"]
        seen = []

        class Api:
            def get_daily_summary(self, d): ...
            def get_spo2(self, d): ...
            def get_hydration(self, a, b): ...
            def get_heart_rate(self, d): ...
            async def get_body_battery(self, a, b, chunks=None):
                seen.append(chunks)

        calls = co.make_daily_calls(True)(Api(), D)
        stubs.run(calls["body_battery"]())
        self.assertEqual(seen, [288])


class LedgerReload(tha.Env):
    def make_api(self):
        class Api(tha.BackfillApi):
            async def get_body_battery(self, a, b, chunks=None):
                self.requests.append(("body_battery", a))
                if self.errors:
                    raise self.errors.pop(0)
                self.chunks = chunks
                t = ms(a.year, a.month, a.day, 6, 0)
                return bb_payload([(t + i * STEP, 60) for i in range(30)] + [(t + 30 * STEP + k, None) for k in range(5)])

        return Api()

    def only_bb(self):
        self.target_errors = {"heart_rate": "history_sensor_disabled", "spo2": "history_sensor_disabled"}

    def test_days_done_in_the_thin_raster_are_loaded_once_more_others_untouched(self):
        self.keep = 4
        self.only_bb()
        api = self.make_api()
        mgr, _ = tha.make_manager(self, api)
        led = stubs.run(mgr.ledger())
        # old ledger: body_battery days done under the old key, heart rate done as well
        led.data["done"] = {"body_battery": [(D - timedelta(days=n)).isoformat() for n in (2, 3, 4)],
                            "heart_rate": [(D - timedelta(days=n)).isoformat() for n in (2, 3)]}
        self.assertFalse(led.is_done("body_battery", (D - timedelta(days=2)).isoformat()))
        self.assertTrue(led.is_done("heart_rate", (D - timedelta(days=2)).isoformat()))
        stubs.run(mgr.run_backfill(api))
        self.assertEqual(sorted(d for _, d in api.requests), sorted(D - timedelta(days=n) for n in (2, 3, 4)))
        self.assertEqual(api.chunks, 288)
        self.assertEqual(self.count(self.written, "body_battery"), 3 * 30)
        led = stubs.run(mgr.ledger())
        self.assertTrue(all(led.is_done("body_battery", (D - timedelta(days=n)).isoformat()) for n in (2, 3, 4)))
        n = api.n()
        stubs.run(mgr.run_backfill(api))
        self.assertEqual(api.n(), n)  # once only
        self.assertEqual(led.data["done"]["heart_rate"], [(D - timedelta(days=n)).isoformat() for n in (2, 3)])  # untouched

    def test_compacted_day_is_looked_up_in_the_recorder_and_gets_the_new_points(self):
        self.keep = 3
        self.only_bb()
        api = self.make_api()
        mgr, _ = tha.make_manager(self, api)
        led = stubs.run(mgr.ledger())
        day = D - timedelta(days=2)
        iso = day.isoformat()
        t = ms(day.year, day.month, day.day, 6, 0)
        old = [(t, 60.0), (t + 10 * STEP, 60.0), (t + 29 * STEP, 60.0)]  # three thin points, now a mark
        led.record("body_battery", iso, old)
        led.compact("2026-12-31")
        self.assertNotIn("p", led.data["series"]["body_battery"][iso])
        self.recorder_rows[("body_battery", day)] = dict(old)
        stubs.run(mgr.run_backfill(api))
        written = [ts for s, tss in self.written if s == "body_battery" for ts in tss if t <= ts < t + 24 * 3600_000]
        self.assertEqual(len(written), 30 - 3)  # the three old ones are adopted, not written twice
        self.assertFalse(set(written) & {ts for ts, _ in old})
        self.assertEqual(len(led.data["series"]["body_battery"][iso]["p"]), 30)

    def test_detail_day_keeps_its_timestamps(self):
        led = hs.Ledger()
        led.record("body_battery", "d", [(1, 5.0)])
        self.assertFalse(led.drop_thin_mark("body_battery", "d"))
        self.assertTrue(led.knows("body_battery", "d"))

    def test_other_series_marks_are_never_dropped(self):
        led = hs.Ledger()
        led.record("heart_rate", "d", [(1, 5.0)])
        led.compact("2027-01-01")
        self.assertFalse(led.drop_thin_mark("heart_rate", "d"))
        self.assertTrue(led.knows("heart_rate", "d"))

    def test_rate_limit_keeps_the_ledger_consistent(self):
        self.keep = 3
        self.only_bb()
        api = self.make_api()
        api.errors = [tha.api_mod.GarminRateLimitError("429")]
        mgr, _ = tha.make_manager(self, api)
        led = stubs.run(mgr.ledger())
        led.data["done"] = {"body_battery": [(D - timedelta(days=2)).isoformat()]}
        stubs.run(mgr.run_backfill(api))
        self.assertTrue(led.is_done("body_battery", (D - timedelta(days=2)).isoformat()))
        self.assertTrue(led.is_done("body_battery", (D - timedelta(days=3)).isoformat()))
        self.assertEqual(self.sleeps[0], mgr.rate_pause_s)
        self.assertEqual(self.count(self.written, "body_battery"), 30 * 2)  # days 2 and 3 after the pause


if __name__ == "__main__":
    unittest.main()
