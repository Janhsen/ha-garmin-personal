"""Live hourly statistics in the daily coordinator: after a sync, closed hours only, option on/off,
request volume, overwriting, failures (invented numbers)."""

import logging
import sys
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402
from intraday_fakes import bb_payload, hr_payload, ms, spo2_payload  # noqa: E402

logging.disable(logging.CRITICAL)
gp = stubs.load_full()
co = sys.modules["gp_full.coordinator"]
api_mod = sys.modules["gp_full.api"]
TODAY = date(2026, 10, 24)
YESTERDAY = date(2026, 10, 23)


def utc(*args):
    return datetime(*args, tzinfo=UTC)


class FakeApi:
    def __init__(self):
        self.calls = []
        self.sync = "t1"
        self.hr, self.bb, self.spo2 = {}, {}, {}
        self.fail = {}

    def _log(self, name, day):
        self.calls.append((name, day))
        exc = self.fail.get((name, day))
        if exc:
            raise exc

    async def get_daily_summary(self, day):
        return {"lastSyncTimestampGMT": self.sync, "totalSteps": 1}

    async def get_hydration(self, a, b):
        return []

    async def get_heart_rate(self, day):
        self._log("heart_rate", day)
        return self.hr.get(day)

    async def get_body_battery(self, a, b):
        self._log("body_battery", a)
        return self.bb.get(a)

    async def get_spo2(self, day):
        self._log("spo2", day)
        return self.spo2.get(day)

    def n(self, name=None, day=None):
        return len([c for c in self.calls if (name is None or c[0] == name) and (day is None or c[1] == day)])


class Base(unittest.TestCase):
    now = utc(2026, 10, 24, 12, 30)

    def setUp(self):
        stubs.RECORDED.clear()
        self.api = FakeApi()
        self.api.hr[TODAY] = hr_payload([(ms(2026, 10, 24, 0, 5), 50), (ms(2026, 10, 24, 11, 10), 60),
                                         (ms(2026, 10, 24, 11, 50), 80), (ms(2026, 10, 24, 12, 10), 99)])
        self.api.hr[YESTERDAY] = hr_payload([(ms(2026, 10, 23, 22, 10), 70), (ms(2026, 10, 23, 23, 40), 72)])
        self.api.bb[TODAY] = bb_payload([(ms(2026, 10, 24, 11, 10), 70), (ms(2026, 10, 24, 12, 20), 68)])
        self.api.spo2[TODAY] = spo2_payload([(ms(2026, 10, 24, 11, 0), 95), (ms(2026, 10, 24, 12, 0), 90)])
        self.clock = {"now": self.now}
        for name in ("now", "utcnow"):
            orig = getattr(co.dt_util, name)
            setattr(co.dt_util, name, lambda: self.clock["now"])
            self.addCleanup(setattr, co.dt_util, name, orig)

    def make(self, *, hourly=True, attrs=False):
        entry = stubs.FakeEntry(entry_id="E1", title="Alex")
        self.hass = stubs.FakeHass()
        c = co.GarminDailyCoordinator(self.hass, entry, self.api, "daily", timedelta(minutes=5),
                                      co.make_daily_calls(attrs), hourly_stats=hourly)
        return c

    def cycle(self, c):
        """One update plus the background job it started."""
        c.data = stubs.run(self._update(c))
        return c.data

    async def _update(self, c):
        data = await c._async_update_data()
        tasks, self.hass.tasks = self.hass.tasks, []
        for task in tasks:
            await task
        return data

    def rows(self, name):
        """All rows written for one series, in write order: [(start, min, max, mean)]."""
        return [(r.start, r.min, r.max, r.mean) for _, m, rows in stubs.RECORDED
                if m.kw["statistic_id"].endswith("_" + name) for r in rows]


class Writing(Base):
    def test_first_cycle_writes_closed_hours_of_today_and_yesterday(self):
        self.cycle(self.make())
        self.assertEqual(self.rows("heart_rate_hourly"), [
            (utc(2026, 10, 23, 22), 70.0, 70.0, 70.0),
            (utc(2026, 10, 23, 23), 72.0, 72.0, 72.0),
            (utc(2026, 10, 24, 0), 50.0, 50.0, 50.0),
            (utc(2026, 10, 24, 11), 60.0, 80.0, 70.0),
        ])
        # the running hour 12 is not stored, for any series
        self.assertEqual(self.rows("body_battery_hourly"), [(utc(2026, 10, 24, 11), 70.0, 70.0, 70.0)])
        self.assertEqual(self.rows("spo2_hourly"), [(utc(2026, 10, 24, 11), 95.0, 95.0, 95.0)])

    def test_running_hour_never_written_even_when_it_has_points(self):
        self.cycle(self.make())
        for name in ("heart_rate_hourly", "body_battery_hourly", "spo2_hourly"):
            self.assertNotIn(utc(2026, 10, 24, 12), [r[0] for r in self.rows(name)])

    def test_hour_is_written_once_it_has_closed(self):
        c = self.make()
        self.cycle(c)
        self.clock["now"] = utc(2026, 10, 24, 13, 0, 1)
        self.api.sync = "t2"
        self.cycle(c)
        last = [r for r in self.rows("heart_rate_hourly") if r[0] == utc(2026, 10, 24, 12)]
        self.assertEqual(last, [(utc(2026, 10, 24, 12), 99.0, 99.0, 99.0)])

    def test_same_hour_is_rewritten_with_corrected_values(self):
        c = self.make()
        self.cycle(c)
        self.api.hr[TODAY] = hr_payload([(ms(2026, 10, 24, 11, 10), 60), (ms(2026, 10, 24, 11, 50), 80),
                                         (ms(2026, 10, 24, 11, 55), 100)])
        self.api.sync = "t2"
        self.cycle(c)
        eleven = [r for r in self.rows("heart_rate_hourly") if r[0] == utc(2026, 10, 24, 11)]
        self.assertEqual(eleven, [(utc(2026, 10, 24, 11), 60.0, 80.0, 70.0), (utc(2026, 10, 24, 11), 60.0, 100.0, 80.0)])

    def test_statistic_metadata(self):
        self.cycle(self.make())
        ids = {m.kw["statistic_id"] for _, m, _ in stubs.RECORDED}
        self.assertEqual(ids, {"garmin_personal:e1_heart_rate_hourly", "garmin_personal:e1_body_battery_hourly",
                               "garmin_personal:e1_spo2_hourly"})

    def test_placeholders_and_gaps(self):
        self.api.hr[TODAY] = hr_payload([(ms(2026, 10, 24, 3, 10), 0), (ms(2026, 10, 24, 5, 10), 55)])
        self.api.hr[YESTERDAY] = None
        self.cycle(self.make())
        self.assertEqual(self.rows("heart_rate_hourly"), [(utc(2026, 10, 24, 5), 55.0, 55.0, 55.0)])

    def test_nothing_from_garmin_writes_nothing(self):
        self.api.hr, self.api.bb, self.api.spo2 = {}, {}, {}
        self.cycle(self.make())
        self.assertEqual(stubs.RECORDED, [])

    def test_unknown_format_does_not_break_and_other_series_still_written(self):
        self.api.hr[TODAY] = {"surprise": True}
        self.api.hr[YESTERDAY] = "junk"
        data = self.cycle(self.make())
        self.assertEqual(self.rows("heart_rate_hourly"), [])
        self.assertEqual(len(self.rows("spo2_hourly")), 1)
        self.assertIn("summary", data)


class Option(Base):
    def test_off_writes_and_requests_nothing_extra(self):
        c = self.make(hourly=False)
        self.cycle(c)
        self.assertEqual(stubs.RECORDED, [])
        self.assertEqual(self.hass.tasks, [])
        self.assertEqual(self.api.n("heart_rate"), 0)
        self.assertEqual(self.api.n("body_battery"), 0)
        self.assertEqual(self.api.n("spo2"), 1)  # only the sensor's own request

    def test_works_without_the_attribute_option_and_with_it(self):
        for attrs in (False, True):
            stubs.RECORDED.clear()
            self.cycle(self.make(attrs=attrs))
            self.assertEqual(len(self.rows("heart_rate_hourly")), 4, attrs)
            self.assertEqual(len(self.rows("spo2_hourly")), 1, attrs)

    def test_default_of_the_coordinator_is_off(self):
        entry = stubs.FakeEntry(entry_id="E1", title="Alex")
        c = co.GarminDailyCoordinator(stubs.FakeHass(), entry, self.api, "daily", timedelta(minutes=5),
                                      co.make_daily_calls(False))
        self.assertFalse(c._hourly_stats)


class RequestVolume(Base):
    def test_attribute_option_off_costs_one_request_per_series_for_today(self):
        self.cycle(self.make(attrs=False))
        self.assertEqual((self.api.n("heart_rate", TODAY), self.api.n("body_battery", TODAY)), (1, 1))
        self.assertEqual(self.api.n("spo2", TODAY), 1)  # reused from the sensor's request
        self.assertEqual(self.api.n(day=YESTERDAY), 3)  # first run of the day: one per series

    def test_attribute_option_on_reuses_the_existing_requests(self):
        self.cycle(self.make(attrs=True))
        for name in ("heart_rate", "body_battery", "spo2"):
            self.assertEqual(self.api.n(name, TODAY), 1, name)

    def test_unchanged_sync_costs_nothing_more(self):
        c = self.make()
        self.cycle(c)
        before = len(self.api.calls)
        self.cycle(c)
        self.cycle(c)
        self.assertEqual(len(self.api.calls), before)

    def test_new_sync_costs_one_request_per_series_and_yesterday_again_in_the_morning(self):
        c = self.make()
        self.cycle(c)
        self.clock["now"] = utc(2026, 10, 24, 8, 0)  # 08:00 local (stub zone is UTC): before 10:00
        self.api.sync = "t2"
        today_before, yesterday_before = self.api.n(day=TODAY), self.api.n(day=YESTERDAY)
        self.cycle(c)
        # today: the sensor's SpO2 request is reused, heart rate and Body Battery cost one each
        self.assertEqual(self.api.n(day=TODAY) - today_before, 3)
        self.assertEqual(self.api.n(day=YESTERDAY) - yesterday_before, 3)  # yesterday once more, before 10:00

    def test_afternoon_sync_does_not_ask_for_yesterday(self):
        c = self.make()
        self.cycle(c)
        self.api.sync = "t2"
        self.clock["now"] = utc(2026, 10, 24, 15, 0)
        before = self.api.n(day=YESTERDAY)
        self.cycle(c)
        self.assertEqual(self.api.n(day=YESTERDAY), before)

    def test_new_day_asks_for_yesterday_once_even_without_a_sync_change(self):
        c = self.make()
        self.cycle(c)
        nextday = date(2026, 10, 25)
        self.clock["now"] = utc(2026, 10, 25, 0, 5)
        self.api.hr[nextday] = hr_payload([])
        self.cycle(c)
        self.assertEqual(self.api.n("heart_rate", TODAY), 2)  # as "yesterday" of the new day
        self.cycle(c)
        self.assertEqual(self.api.n("heart_rate", TODAY), 2)


class Failures(Base):
    def test_rate_limit_is_swallowed_and_entities_still_update(self):
        self.api.fail[("heart_rate", TODAY)] = api_mod.GarminRateLimitError("429")
        data = self.cycle(self.make())
        self.assertIn("summary", data)
        self.assertEqual(stubs.RECORDED, [])
        self.assertEqual(self.api.n("body_battery"), 0)  # no hammering after the limit

    def test_other_error_skips_only_that_series(self):
        self.api.fail[("heart_rate", TODAY)] = api_mod.GarminApiError("x", 500)
        self.cycle(self.make())
        self.assertEqual(self.rows("heart_rate_hourly"), [])
        self.assertEqual(len(self.rows("body_battery_hourly")), 1)
        self.assertEqual(len(self.rows("spo2_hourly")), 1)

    def test_failed_yesterday_is_tried_again_at_the_next_run(self):
        self.api.fail[("body_battery", YESTERDAY)] = api_mod.GarminApiError("x", 500)
        c = self.make()
        self.cycle(c)
        self.api.fail.clear()
        self.api.sync = "t2"
        self.clock["now"] = utc(2026, 10, 24, 15, 0)  # afternoon: only because it failed
        before = self.api.n(day=YESTERDAY)
        self.cycle(c)
        self.assertEqual(self.api.n(day=YESTERDAY) - before, 3)

    def test_unexpected_exception_is_swallowed(self):
        c = self.make()

        orig = co.write_hourly
        co.write_hourly = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            data = self.cycle(c)
        finally:
            co.write_hourly = orig
        self.assertIn("summary", data)

    def test_jobs_do_not_overlap(self):
        c = self.make()
        self.cycle(c)
        self.assertIsNotNone(c._intraday_lock)
        self.assertFalse(c._intraday_lock.locked())


class Privacy(Base):
    def test_series_do_not_end_up_in_data_or_logs(self):
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)
        self.api.fail[("body_battery", TODAY)] = api_mod.GarminApiError("x", 500)
        self.api.hr[TODAY] = hr_payload([(ms(2026, 10, 24, 11, 10), 4711)])
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger("x").debug("start")
            data = self.cycle(self.make(attrs=False))
        self.assertNotIn("4711", "\n".join(logs.output))
        self.assertNotIn("heart_rate", data)  # option off: the series is not kept in the coordinator data


if __name__ == "__main__":
    unittest.main()
