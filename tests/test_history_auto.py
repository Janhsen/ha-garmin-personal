"""Automatic history: live appending after a sync and the throttled initial load (fakes, invented numbers)."""

import logging
import sys
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402
import test_intraday_coordinator as tic  # noqa: E402
from intraday_fakes import hr_payload, ms, spo2_payload  # noqa: E402

logging.disable(logging.CRITICAL)
hs = sys.modules["gp_full.history"]
co = sys.modules["gp_full.coordinator"]
rep = sys.modules["gp_full.repairs"]
api_mod = sys.modules["gp_full.api"]
sn = sys.modules["gp_full.sensor"]
D = date(2026, 10, 24)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


class Env(unittest.TestCase):
    """Patches the target check, the recorder reader and the writer; records what is written."""

    active = ("heart_rate", "spo2", "body_battery")

    def setUp(self):
        stubs.Store.instances.clear()
        stubs.Store.preset = None
        self.written = []  # (series, [ts...])
        self.target_errors = {}  # series -> HistoryTargetError key
        self.issues = []
        self.recorder_rows = {}
        self.today = D
        self.write_error = None

        async def check(hass, entry, series):
            key = self.target_errors.get(series)
            if key:
                raise hs.HistoryTargetError(key, "sensor.x")
            return f"sensor.alex_{series}_history"

        async def writer(hass, entry, series, points):
            if self.write_error:
                return 0, self.write_error
            self.written.append((series, [ts for ts, _ in points]))
            return len(points), None

        async def reader(hass, entry, series, day):
            return self.recorder_rows.get((series, day), {})

        self.patch(hs, "check_target", check)
        self.patch(hs, "write_history_states", writer)
        self.patch(hs, "recorded_points", reader)
        self.patch(rep, "update_history_issue", lambda hass, entry, series, excluded: self.issues.append((series, excluded)))
        self.patch(hs.dt_util, "now", lambda: datetime(self.today.year, self.today.month, self.today.day, 12, tzinfo=UTC))
        self.patch(hs, "recorder_keep_days", lambda hass: self.keep)
        self.keep = 3

    def patch(self, obj, name, value):
        orig = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, orig)

    def count(self, written, series):
        return sum(len(ts) for s, ts in written if s == series)


class BackfillApi:
    def __init__(self):
        self.requests = []  # (series, day)
        self.hr, self.spo2 = {}, {}
        self.errors = []  # queue of exceptions to raise on the next requests

    def _go(self, name, store, day):
        self.requests.append((name, day))
        if self.errors:
            raise self.errors.pop(0)
        return store.get(day)

    async def get_heart_rate(self, day):
        return self._go("heart_rate", self.hr, day)

    async def get_spo2(self, day):
        return self._go("spo2", self.spo2, day)

    async def get_body_battery(self, a, b):
        return self._go("body_battery", {}, a)

    def n(self, series=None):
        return len([r for r in self.requests if series in (None, r[0])])


def make_manager(env, api=None):
    entry = stubs.FakeEntry(entry_id="E1", title="Alex", runtime_data=SimpleNamespace(api=api))
    hass = stubs.FakeHass()
    mgr = hs.manager_for(hass, entry)
    env.sleeps = []

    async def sleep(seconds):
        env.sleeps.append(seconds)

    mgr.sleep = sleep
    return mgr, entry


class InitialLoad(Env):
    def run_load(self, mgr, api):
        stubs.run(mgr.run_backfill(api))

    def test_goes_back_from_yesterday_one_day_per_throttle_and_never_marks_today(self):
        api = BackfillApi()
        for n in (1, 2, 3):
            day = D - timedelta(days=n)
            api.hr[day] = hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)])
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        days = [d for s, d in api.requests if s == "heart_rate"]
        self.assertEqual(days, [D - timedelta(days=n) for n in (1, 2, 3)])  # newest first, today excluded
        self.assertEqual(self.sleeps, [20, 20, 20])
        self.assertEqual(self.count(self.written, "heart_rate"), 3)
        led = stubs.run(mgr.ledger())
        self.assertFalse(led.is_done("heart_rate", D.isoformat()))
        self.assertTrue(all(led.is_done("heart_rate", (D - timedelta(days=n)).isoformat()) for n in (1, 2, 3)))
        self.assertEqual(mgr.progress["heart_rate"], {"history_backfilled_until": "2026-10-21"})
        self.assertEqual(api.n("spo2"), 0)  # disabled series: silently nothing

    def test_resume_after_restart_asks_nothing_twice(self):
        api = BackfillApi()
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        first = api.n()
        stubs.Store.preset = stubs.Store.instances[-1].saved[-1]  # what is on disk
        mgr2, _ = make_manager(self, api)  # a restart: new manager, same store
        self.run_load(mgr2, api)
        self.assertEqual(api.n(), first)

    def test_stops_after_14_empty_days_and_remembers_it(self):
        self.keep = 60
        api = BackfillApi()
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        self.assertEqual(api.n("heart_rate"), 14)
        self.run_load(mgr, api)
        self.assertEqual(api.n("heart_rate"), 14)  # done days and the floor: no new request

    def test_data_resets_the_empty_streak(self):
        self.keep = 40
        api = BackfillApi()
        for n in range(1, 41):
            if n in (10, 20):
                day = D - timedelta(days=n)
                api.hr[day] = hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)])
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        self.assertEqual(api.n("heart_rate"), 20 + 14)  # 14 empty days after the last day with data

    def test_rate_limit_pauses_30_minutes_and_retries_the_same_day(self):
        self.keep = 1
        api = BackfillApi()
        api.errors = [api_mod.GarminRateLimitError("429")]
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        self.assertEqual(self.sleeps[0], 1800)
        self.assertEqual([d for _, d in api.requests], [D - timedelta(days=1)] * 2)

    def test_auth_error_and_repeated_errors_stop_without_marking_days(self):
        self.keep = 5
        for errors in ([api_mod.GarminAuthError("bad")], [api_mod.GarminApiError("x", 500)] * 5):
            api = BackfillApi()
            api.errors = list(errors)
            mgr, _ = make_manager(self, api)
            self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
            self.run_load(mgr, api)
            self.assertFalse(stubs.run(mgr.ledger()).is_done("heart_rate", (D - timedelta(days=1)).isoformat()))
            self.assertLessEqual(api.n(), 3)

    def test_write_error_or_unreadable_recorder_stops_and_marks_nothing(self):
        self.keep = 3
        day = D - timedelta(days=1)
        api = BackfillApi()
        api.hr[day] = hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)])
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.write_error = "boom"
        self.run_load(mgr, api)
        self.assertEqual(api.n(), 1)
        self.assertFalse(stubs.run(mgr.ledger()).is_done("heart_rate", day.isoformat()))
        self.write_error = None

        async def unreadable(hass, entry, series, d):
            raise hs.HistoryWriteUnsupported("no")

        self.patch(hs, "recorded_points", unreadable)
        mgr2, _ = make_manager(self, api)
        self.run_load(mgr2, api)
        self.assertEqual(self.written, [])
        self.assertFalse(stubs.run(mgr2.ledger()).is_done("heart_rate", day.isoformat()))

    def test_unknown_format_stops_the_series(self):
        api = BackfillApi()
        api.hr[D - timedelta(days=1)] = {"surprise": 1}
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        self.assertEqual(api.n(), 1)

    def test_never_parallel_to_the_services(self):
        import asyncio

        api = BackfillApi()
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}

        async def scenario():
            async with mgr.lock:  # a backfill service is running
                task = asyncio.ensure_future(mgr.run_backfill(api))
                for _ in range(10):
                    await asyncio.sleep(0)
                self.assertEqual(api.n(), 0)
            await task

        stubs.run(scenario())
        self.assertGreater(api.n(), 0)

    def test_enabling_a_series_later_loads_everything_back_to_the_limit_without_repeating_the_other(self):
        api = BackfillApi()
        for series_store in (api.hr, api.spo2):
            for n in range(0, 8):
                day = D - timedelta(days=n)
                series_store[day] = hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)]) if series_store is api.hr \
                    else spo2_payload([(ms(day.year, day.month, day.day, 8, 0), 95)])
        mgr, _ = make_manager(self, api)
        # run 1: only SpO2 is enabled; days 23, 22, 21 are loaded
        self.target_errors = {"heart_rate": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        self.assertEqual((api.n("spo2"), api.n("heart_rate")), (3, 0))
        # two days pass, the heart rate sensor gets enabled (the entry reloads)
        self.today = D + timedelta(days=2)
        self.target_errors = {"body_battery": "history_sensor_disabled"}
        api.requests.clear()
        self.run_load(mgr, api)
        today = self.today
        self.assertEqual(sorted(d for s, d in api.requests if s == "heart_rate"),
                         [today - timedelta(days=n) for n in (3, 2, 1)])  # full load up to the limit
        self.assertEqual(sorted(d for s, d in api.requests if s == "spo2"),
                         [today - timedelta(days=2), today - timedelta(days=1)])  # only the new gap, day 23 is done

    def test_recorder_exclusion_gives_a_repair_hint_only_then(self):
        api = BackfillApi()
        mgr, _ = make_manager(self, api)
        self.target_errors = {"heart_rate": "history_not_recorded", "spo2": "history_sensor_disabled",
                              "body_battery": "history_sensor_missing"}
        stubs.run(mgr.active_series())
        self.assertEqual(dict(self.issues), {"heart_rate": True, "spo2": False, "body_battery": False})

    def test_progress_attribute_is_small_and_on_the_sensor(self):
        api = BackfillApi()
        mgr, entry = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        sensor = sn.GarminHistorySensor(entry, "heart_rate_history", "bpm")
        self.assertEqual(sensor.extra_state_attributes, {"history_backfilled_until": "2026-10-21"})
        other = sn.GarminHistorySensor(entry, "spo2_history", "%")
        self.assertIsNone(other.extra_state_attributes)

    def test_ensure_backfill_starts_one_background_task(self):
        api = BackfillApi()
        mgr, entry = make_manager(self, api)
        started = []

        class Task:
            def done(self):
                return False

        entry.async_create_background_task = lambda hass, coro, name: (started.append(coro), Task())[1]
        mgr.ensure_backfill(api)
        mgr.ensure_backfill(api)
        self.assertEqual(len(started), 1)
        started[0].close()

    def test_no_background_support_is_not_an_error(self):
        mgr, entry = make_manager(self, BackfillApi())
        mgr.ensure_backfill(BackfillApi())  # FakeEntry has no async_create_background_task


class DisplayName(unittest.TestCase):
    def test_names(self):
        sw = sys.modules["gp_full.stats_writer"]
        self.assertEqual(sw.display_name("Alex", "heart_rate_hourly"), "Alex heart rate (hourly)")
        self.assertEqual(sw.display_name("Alex", "steps"), "Alex steps")


class KeepDays(unittest.TestCase):
    def test_rules(self):
        real = sys.modules["gp_full.history"].recorder_keep_days
        rec = sys.modules["homeassistant.components.recorder"]
        had = hasattr(rec, "get_instance")
        old = getattr(rec, "get_instance", None)
        self.addCleanup(lambda: setattr(rec, "get_instance", old) if had else delattr(rec, "get_instance"))
        for value, expected in ((7, 7), (None, 10), (0, 10), (True, 10), ("5", 10), (1000, 400), (400, 400)):
            rec.get_instance = lambda hass, v=value: SimpleNamespace(keep_days=v)
            self.assertEqual(real(object()), expected, value)
        rec.get_instance = lambda hass: (_ for _ in ()).throw(KeyError("no recorder"))
        self.assertEqual(real(object()), 10)


class Live(Env, tic.Base):
    def setUp(self):
        tic.Base.setUp(self)
        Env.setUp(self)
        self.patch(hs.dt_util, "now", lambda: self.clock["now"])

    def make(self, *, hourly=True, auto=True):
        entry = stubs.FakeEntry(entry_id="E1", title="Alex", runtime_data=SimpleNamespace(api=self.api))
        self.hass = stubs.FakeHass()
        self.entry = entry
        c = co.GarminDailyCoordinator(self.hass, entry, self.api, "daily", timedelta(minutes=5),
                                      co.make_daily_calls(False), hourly_stats=hourly, history_auto=auto)
        mgr = hs.manager_for(self.hass, entry)
        self.mgr = mgr

        async def nosleep(seconds):
            pass

        mgr.sleep = nosleep
        return c

    def hist(self, series):
        return [ts for s, tss in self.written for ts in tss if s == series]

    def test_new_points_of_today_and_yesterday_are_appended(self):
        self.cycle(self.make())
        hr = self.hist("heart_rate")
        self.assertEqual(len(hr), 4 + 2)  # today 4 (the running hour too: history has no hour logic) + yesterday 2
        self.assertEqual(hr, sorted(hr[:2]) + sorted(hr[2:]))  # yesterday first, then today, each ascending
        self.assertFalse(stubs.run(self.mgr.ledger()).is_done("heart_rate", TODAY_ISO))

    def test_second_sync_appends_only_what_is_new_even_if_older(self):
        c = self.make()
        self.cycle(c)
        before = len(self.hist("heart_rate"))
        self.api.hr[tic.TODAY] = hr_payload([(ms(2026, 10, 24, 0, 5), 50), (ms(2026, 10, 24, 0, 6), 51),  # late older point
                                              (ms(2026, 10, 24, 11, 10), 60), (ms(2026, 10, 24, 11, 50), 80),
                                              (ms(2026, 10, 24, 12, 10), 99), (ms(2026, 10, 24, 12, 20), 98)])
        self.api.sync = "t2"
        self.cycle(c)
        new = self.hist("heart_rate")[before:]
        self.assertEqual(sorted(new), sorted([ms(2026, 10, 24, 0, 6), ms(2026, 10, 24, 12, 20)]))

    def test_unchanged_sync_writes_nothing_and_asks_nothing(self):
        c = self.make()
        self.cycle(c)
        calls, written = len(self.api.calls), len(self.written)
        self.cycle(c)
        self.assertEqual((len(self.api.calls), len(self.written)), (calls, written))

    def test_history_shares_the_requests_of_the_hourly_job(self):
        self.cycle(self.make(hourly=True, auto=True))
        with_both = len(self.api.calls)
        self.api.calls.clear()
        stubs.RECORDED.clear()
        self.cycle(self.make(hourly=True, auto=False))
        self.assertEqual(len(self.api.calls), with_both)

    def test_history_only_asks_for_the_active_series(self):
        self.target_errors = {"body_battery": "history_sensor_disabled", "spo2": "history_sensor_disabled"}
        self.cycle(self.make(hourly=False, auto=True))
        self.assertEqual({n for n, _ in self.api.calls} - {"spo2"}, {"heart_rate"})  # spo2 only from the sensor's own call
        self.assertEqual(self.api.n("body_battery"), 0)

    def test_option_off_checks_and_writes_nothing(self):
        self.cycle(self.make(hourly=True, auto=False))
        self.assertEqual(self.written, [])
        self.assertEqual(self.issues, [])
        self.assertTrue(all(not getattr(i, 'saved', None) for i in stubs.Store.instances))

    def test_sensor_not_enabled_keeps_the_hourly_statistics_working(self):
        self.target_errors = dict.fromkeys(("heart_rate", "spo2", "body_battery"), "history_sensor_disabled")
        self.cycle(self.make())
        self.assertEqual(self.written, [])
        self.assertTrue(self.rows("heart_rate_hourly"))

    def test_start_of_the_initial_load_is_requested_by_the_job(self):
        c = self.make()
        started = []
        self.entry.async_create_background_task = lambda hass, coro, name: (started.append(name), coro.close())[0]
        self.cycle(c)
        self.assertEqual(len(started), 1)

    def test_write_failure_is_swallowed(self):
        self.write_error = "boom"
        data = self.cycle(self.make())
        self.assertIn("summary", data)
        self.assertTrue(self.rows("heart_rate_hourly"))


TODAY_ISO = "2026-10-24"

if __name__ == "__main__":
    unittest.main()
