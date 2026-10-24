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
from intraday_fakes import hr_payload, hrv_payload, ms, spo2_payload  # noqa: E402

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
        self.hrv_on = False  # the HRV sensor stays disabled unless a test enables it

        async def check(hass, entry, series):
            key = self.target_errors.get(series)
            if series == "hrv" and not self.hrv_on:
                key = "history_sensor_disabled"
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

    async def get_hrv(self, day):
        return self._go("hrv", getattr(self, "hrv", {}), day)

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


class LedgerAndCancel(Env):
    def test_concurrent_first_access_gives_one_ledger(self):
        import asyncio

        mgr, _ = make_manager(self)
        loads = []
        orig = mgr._store.async_load

        async def slow_load():
            loads.append(1)
            await asyncio.sleep(0.01)
            return await orig()

        mgr._store.async_load = slow_load

        async def both():
            return await asyncio.gather(mgr.ledger(), mgr.ledger(), mgr.ledger())

        ledgers = stubs.run(both())
        self.assertIs(ledgers[0], ledgers[1])
        self.assertIs(ledgers[1], ledgers[2])
        self.assertEqual(len(loads), 1)

    def test_cancelled_write_notes_the_points_already_handed_over(self):
        mgr, entry = make_manager(self)
        pts = [(ms(2026, 10, 24, 8, i), 60.0 + i) for i in range(10)]
        led = stubs.run(mgr.ledger())
        calls = []

        async def cancelled_after_four(hass, entry, series, points):
            calls.append([ts for ts, _ in points])
            raise hs.HistoryWriteCancelled(4)

        self.patch(hs, "write_history_states", cancelled_after_four)

        async def run():
            async with mgr.persisting():
                await hs.append_points(None, entry, led, "heart_rate", D, pts)

        with self.assertRaises(__import__("asyncio").CancelledError):
            stubs.run(run())
        saved = stubs.Store.instances[-1].saved[-1]  # the ledger was saved on the way out
        self.assertEqual(sorted(int(t) for t in saved["series"]["heart_rate"][D.isoformat()]["p"]),
                         [ts for ts, _ in pts[:4]])
        # after a reload the next run writes only the rest
        stubs.Store.preset = saved
        mgr2, entry2 = make_manager(self)
        led2 = stubs.run(mgr2.ledger())
        rest = []

        async def writer(hass, entry, series, points):
            rest.extend(ts for ts, _ in points)
            return len(points), None

        self.patch(hs, "write_history_states", writer)
        res = stubs.run(hs.append_points(None, entry2, led2, "heart_rate", D, pts))
        self.assertEqual((res.written, res.already), (6, 4))
        self.assertEqual(sorted(rest), [ts for ts, _ in pts[4:]])

    def test_stop_cancels_the_running_initial_load(self):
        import asyncio

        mgr, _ = make_manager(self)

        async def scenario():
            started = asyncio.Event()

            async def forever():
                started.set()
                await asyncio.sleep(3600)

            mgr._task = asyncio.ensure_future(forever())
            await started.wait()
            await mgr.async_stop()
            return mgr._task.cancelled()

        self.assertTrue(stubs.run(scenario()))


class InitialLoad(Env):
    def run_load(self, mgr, api):
        stubs.run(mgr.run_backfill(api))

    def test_goes_back_from_the_day_before_yesterday_one_day_per_throttle(self):
        self.keep = 4
        api = BackfillApi()
        for n in (1, 2, 3, 4):
            day = D - timedelta(days=n)
            api.hr[day] = hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)])
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        days = [d for s, d in api.requests if s == "heart_rate"]
        self.assertEqual(days, [D - timedelta(days=n) for n in (2, 3, 4)])  # newest first, yesterday is the live path's
        self.assertEqual(self.sleeps, [20, 20, 20])
        self.assertEqual(self.count(self.written, "heart_rate"), 3)
        led = stubs.run(mgr.ledger())
        self.assertFalse(led.is_done("heart_rate", D.isoformat()))
        self.assertFalse(led.is_done("heart_rate", (D - timedelta(days=1)).isoformat()))  # may still be incomplete
        self.assertTrue(all(led.is_done("heart_rate", (D - timedelta(days=n)).isoformat()) for n in (2, 3, 4)))
        self.assertEqual(mgr.progress["heart_rate"], {"history_backfilled_until": "2026-10-20"})
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
        self.assertEqual(api.n("heart_rate"), 19 + 14)  # from the day before yesterday; 14 empty days after the last data

    def test_rate_limit_pauses_30_minutes_and_retries_the_same_day(self):
        self.keep = 2
        api = BackfillApi()
        api.errors = [api_mod.GarminRateLimitError("429")]
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        self.assertEqual(self.sleeps[0], 1800)
        self.assertEqual([d for _, d in api.requests], [D - timedelta(days=2)] * 2)

    def test_auth_error_and_repeated_errors_stop_without_marking_days(self):
        self.keep = 5
        for errors in ([api_mod.GarminAuthError("bad")], [api_mod.GarminApiError("x", 500)] * 9):
            api = BackfillApi()
            api.errors = list(errors)
            mgr, _ = make_manager(self, api)
            self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
            self.run_load(mgr, api)
            led = stubs.run(mgr.ledger())
            self.assertFalse(any(led.is_done("heart_rate", (D - timedelta(days=n)).isoformat()) for n in range(1, 6)))
            self.assertLessEqual(api.n(), 6)  # an auth error at once, otherwise two bad days of three tries each

    def test_a_day_that_keeps_failing_is_put_off_and_the_load_goes_on(self):
        self.keep = 8
        bad = D - timedelta(days=4)

        class Api(BackfillApi):
            async def get_heart_rate(self, day):
                self.requests.append(("heart_rate", day))
                if day == bad:
                    raise api_mod.GarminApiError("HTTP 500", 500)
                return hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)])

        api = Api()
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        led = stubs.run(mgr.ledger())
        asked = [d for _, d in api.requests]
        self.assertEqual(asked.count(bad), 3)  # three tries, then it is put off
        self.assertIn(D - timedelta(days=8), asked)  # everything behind it was loaded
        self.assertFalse(led.is_done("heart_rate", bad.isoformat()))
        self.assertTrue(led.is_deferred("heart_rate", bad.isoformat(), D))
        n = api.n()
        self.run_load(mgr, api)
        self.assertEqual(api.n(), n)  # not asked again the same day
        self.today = D + timedelta(days=1)  # the next day it gets another chance, with a longer wait after that
        self.run_load(mgr, api)
        self.assertEqual([d for _, d in api.requests[n:]].count(bad), 3)
        led = stubs.run(mgr.ledger())
        self.assertTrue(led.is_deferred("heart_rate", bad.isoformat(), D + timedelta(days=2)))

    def test_two_bad_days_in_a_row_end_the_run_but_not_the_next_one(self):
        self.keep = 8
        bad = {D - timedelta(days=2), D - timedelta(days=3)}

        class Api(BackfillApi):
            async def get_heart_rate(self, day):
                self.requests.append(("heart_rate", day))
                if day in bad:
                    raise api_mod.GarminApiError("HTTP 500", 500)
                return hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)])

        api = Api()
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        self.assertEqual(api.n(), 6)
        self.run_load(mgr, api)  # the bad days are skipped, the rest is loaded
        self.assertIn(D - timedelta(days=8), [d for _, d in api.requests])

    def test_empty_answers_do_not_finish_days_and_the_floor_lapses(self):
        self.keep = 60
        api = BackfillApi()  # every day: no body at all (HTTP 204)
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        led = stubs.run(mgr.ledger())
        self.assertEqual(api.n(), 14)
        self.assertFalse(any(led.is_done("heart_rate", (D - timedelta(days=n)).isoformat()) for n in range(2, 16)))
        self.assertIsNotNone(led.floor("heart_rate", D))
        self.run_load(mgr, api)
        self.assertEqual(api.n(), 14)  # asked again only after a week
        for n in range(2, 60):  # Garmin has data after all
            day = D - timedelta(days=n)
            api.hr[day] = hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)])
        self.today = D + timedelta(days=8)
        self.run_load(mgr, api)
        self.assertGreater(self.count(self.written, "heart_rate"), 14)
        self.assertTrue(stubs.run(mgr.ledger()).is_done("heart_rate", (D - timedelta(days=2)).isoformat()))

    def test_real_empty_days_are_done_and_the_floor_stays(self):
        self.keep = 60
        api = BackfillApi()
        for n in range(2, 60):
            api.hr[D - timedelta(days=n)] = hr_payload([])  # Garmin answers: nothing measured
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        self.run_load(mgr, api)
        led = stubs.run(mgr.ledger())
        self.assertTrue(all(led.is_done("heart_rate", (D - timedelta(days=n)).isoformat()) for n in range(2, 16)))
        self.today = D + timedelta(days=30)
        self.assertIsNotNone(led.floor("heart_rate", self.today))

    def test_a_floor_from_an_older_version_does_not_hold(self):
        led = hs.Ledger({"v": 1, "series": {}, "floor": {"heart_rate": "2026-10-01"}})
        self.assertIsNone(led.floor("heart_rate", D))

    def test_write_error_or_unreadable_recorder_stops_and_marks_nothing(self):
        self.keep = 3
        day = D - timedelta(days=2)
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
        api.hr[D - timedelta(days=2)] = {"surprise": 1}
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
        self.keep = 4
        api = BackfillApi()
        for series_store in (api.hr, api.spo2):
            for n in range(0, 8):
                day = D - timedelta(days=n)
                series_store[day] = hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)]) if series_store is api.hr \
                    else spo2_payload([(ms(day.year, day.month, day.day, 8, 0), 95)])
        mgr, _ = make_manager(self, api)
        # run 1: only SpO2 is enabled; days 22, 21, 20 are loaded
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
                         [today - timedelta(days=n) for n in (4, 3, 2)])  # full load up to the limit
        self.assertEqual(sorted(d for s, d in api.requests if s == "spo2"),
                         [today - timedelta(days=3), today - timedelta(days=2)])  # only the new gap, day 22 is done

    def test_recorder_exclusion_gives_a_repair_hint_only_then(self):
        api = BackfillApi()
        mgr, _ = make_manager(self, api)
        self.target_errors = {"heart_rate": "history_not_recorded", "spo2": "history_sensor_disabled",
                              "body_battery": "history_sensor_missing"}
        stubs.run(mgr.active_series())
        self.assertEqual(dict(self.issues), {"heart_rate": True, "spo2": False, "body_battery": False, "hrv": False})

    def test_progress_attribute_is_small_and_on_the_sensor(self):
        api = BackfillApi()
        for n in (2, 3):
            day = D - timedelta(days=n)
            api.hr[day] = hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)])
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


class LiveBase(Env, tic.Base):
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



class Live(LiveBase):
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

        class Task:
            def done(self):
                return False

            def add_done_callback(self, callback):
                pass

        def create(hass, coro, name):
            started.append(name)
            if "history load" in name:
                coro.close()
            else:
                self.hass.tasks.append(coro)  # the side job itself runs inside the cycle
            return Task()

        self.entry.async_create_background_task = create
        self.cycle(c)
        self.assertEqual(sorted(n.split(" ", 1)[1] for n in started), ["history load", "intraday job"])

    def test_write_failure_is_swallowed(self):
        self.write_error = "boom"
        data = self.cycle(self.make())
        self.assertIn("summary", data)
        self.assertTrue(self.rows("heart_rate_hourly"))


def night(day, n=3, first=(22, 0)):
    """An invented HRV night that ends on the morning of ``day``: readings from the evening before into the morning."""
    prev = day - timedelta(days=1)
    start = datetime(prev.year, prev.month, prev.day, *first)
    rows = []
    for i in range(n):
        t = start + timedelta(minutes=5 * i + 60 * (i // 2))
        rows.append((t.strftime("%Y-%m-%dT%H:%M:%S.0"), 40 + i))
    return rows


class HrvHistory(Env):
    def only_hrv(self):
        self.hrv_on = True
        self.target_errors = {"heart_rate": "history_sensor_disabled", "spo2": "history_sensor_disabled",
                              "body_battery": "history_sensor_disabled"}

    def test_window_of_a_night_is_noon_to_noon_of_the_wake_day(self):
        a, b = hs.series_window("hrv", D)
        self.assertEqual((a, b), (datetime(2026, 10, 23, 12, tzinfo=UTC), datetime(2026, 10, 24, 12, tzinfo=UTC)))
        a, b = hs.series_window("heart_rate", D)
        self.assertEqual((a, b), (datetime(2026, 10, 24, tzinfo=UTC), datetime(2026, 10, 25, tzinfo=UTC)))
        self.assertEqual(hs._unit_of("hrv"), "ms")

    def test_initial_load_writes_whole_nights_under_the_wake_day(self):
        self.only_hrv()
        self.keep = 3
        api = BackfillApi()
        api.hrv = {D - timedelta(days=n): hrv_payload(night(D - timedelta(days=n))) for n in (2, 3)}
        mgr, _ = make_manager(self, api)
        stubs.run(mgr.run_backfill(api))
        self.assertEqual([d for s, d in api.requests], [D - timedelta(days=2), D - timedelta(days=3)])
        stamps = [t for s, ts in self.written if s == "hrv" for t in ts]
        self.assertEqual(len(stamps), 6)
        led = stubs.run(mgr.ledger())
        wake = (D - timedelta(days=2)).isoformat()
        self.assertTrue(led.knows("hrv", wake) and led.is_done("hrv", wake))
        self.assertTrue(any(t < ms(2026, 10, 23, 0, 0) for t in stamps))  # the evening before the wake day
        self.assertFalse(led.knows("hrv", D.isoformat()))
        self.assertEqual(mgr.progress["hrv"], {"history_backfilled_until": (D - timedelta(days=3)).isoformat()})

    def test_service_and_recorder_check_use_the_night_window(self):
        self.only_hrv()
        seen = []

        async def reader(hass, entry, series, day):
            seen.append((series, day))
            return {ms(2026, 10, 23, 22, 0): 40.0}  # already in the recorder (from the evening before)

        self.patch(hs, "recorded_points", reader)
        api = BackfillApi()
        api.hrv = {D: hrv_payload(night(D))}
        mgr, entry = make_manager(self, api)
        led = stubs.run(mgr.ledger())
        res = stubs.run(hs.append_points(mgr.hass, entry, led, "hrv", D, hs.HISTORY_SERIES["hrv"].parse(api.hrv[D])))
        self.assertEqual((res.adopted, res.already, res.written), (1, 1, 2))
        self.assertEqual(seen, [("hrv", D)])

    def test_enabling_hrv_later_loads_it_to_the_limit_without_asking_heart_rate_again(self):
        self.keep = 4
        api = BackfillApi()
        for n in range(0, 8):
            day = D - timedelta(days=n)
            api.hr[day] = hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)])
            api.hrv = {**getattr(api, "hrv", {}), day: hrv_payload(night(day))}
        mgr, _ = make_manager(self, api)
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        stubs.run(mgr.run_backfill(api))  # heart rate only (hrv disabled)
        self.assertEqual((api.n("heart_rate"), api.n("hrv")), (3, 0))
        self.today = D + timedelta(days=2)
        self.hrv_on = True
        api.requests.clear()
        stubs.run(mgr.run_backfill(api))
        today = self.today
        self.assertEqual(sorted(d for s, d in api.requests if s == "hrv"), [today - timedelta(days=n) for n in (4, 3, 2)])
        self.assertEqual(sorted(d for s, d in api.requests if s == "heart_rate"),
                         [today - timedelta(days=3), today - timedelta(days=2)])
        api.requests.clear()
        stubs.run(mgr.run_backfill(api))
        self.assertEqual(api.requests, [])  # everything is done


class LateSync(LiveBase):
    def test_sync_after_midnight_brings_yesterdays_evening_even_after_ten(self):
        self.api.sync = "2026-10-23T18:00:00.0"
        self.clock["now"] = utc(2026, 10, 24, 0, 30)
        c = self.make()
        self.cycle(c)  # the first run of the day
        first = len(self.hist("heart_rate"))
        evening = ms(2026, 10, 23, 23, 50)
        self.api.hr[tic.YESTERDAY] = hr_payload([(ms(2026, 10, 23, 22, 10), 70), (ms(2026, 10, 23, 23, 40), 72),
                                                  (evening, 74)])
        self.api.sync = "2026-10-24T11:00:00.0"  # the phone connects at 11 o'clock
        self.clock["now"] = utc(2026, 10, 24, 11, 5)
        before = self.api.n("heart_rate", tic.YESTERDAY)
        self.cycle(c)
        self.assertEqual(self.api.n("heart_rate", tic.YESTERDAY), before + 1)
        self.assertIn(evening, self.hist("heart_rate")[first:])
        self.assertEqual(len(set(self.hist("heart_rate"))), len(self.hist("heart_rate")))  # nothing twice

    def test_later_syncs_of_the_day_do_not_ask_again(self):
        self.api.sync = "2026-10-23T18:00:00.0"
        c = self.make()
        self.cycle(c)
        self.api.sync = "2026-10-24T11:00:00.0"
        self.clock["now"] = utc(2026, 10, 24, 11, 5)
        self.cycle(c)
        before = self.api.n("heart_rate", tic.YESTERDAY)
        self.api.sync = "2026-10-24T15:00:00.0"  # the previous sync was today: yesterday is complete
        self.clock["now"] = utc(2026, 10, 24, 15, 5)
        self.cycle(c)
        self.assertEqual(self.api.n("heart_rate", tic.YESTERDAY), before)

    def test_the_job_is_bound_to_the_entry_and_stopped_with_it(self):
        import asyncio

        c = self.make()
        started = []

        async def scenario():
            loop = asyncio.get_running_loop()

            def create(hass, coro, name):
                started.append(name)
                return loop.create_task(coro, name=name)

            self.entry.async_create_background_task = create
            gate = asyncio.Event()

            async def blocked():
                await gate.wait()

            c._start_job(blocked())
            await asyncio.sleep(0)
            alive = len(c._jobs)
            await c.async_stop_jobs()
            await asyncio.sleep(0)
            return alive, len(c._jobs)

        self.assertEqual(stubs.run(scenario()), (1, 0))
        self.assertEqual(started, ["garmin_personal intraday job"])
        self.assertEqual(self.hass.tasks, [])  # nothing went to the loose hass task list


class HrvLive(LiveBase):
    def setUp(self):
        super().setUp()
        self.hrv_on = True
        self.target_errors = dict.fromkeys(("heart_rate", "spo2", "body_battery"), "history_sensor_disabled")

    def test_the_night_is_completed_by_later_syncs_and_only_new_points_are_appended(self):
        day, prev = tic.TODAY, tic.YESTERDAY
        self.api.hrv[prev] = hrv_payload(night(prev, 4))
        self.api.hrv[day] = hrv_payload(night(day, 2))  # woke up, not complete yet
        c = self.make()
        self.cycle(c)
        first = self.hist("hrv")
        self.assertEqual(len(first), 4 + 2)
        self.api.hrv[day] = hrv_payload(night(day, 5))  # the full night arrives later
        self.api.sync = "t2"
        self.cycle(c)
        later = self.hist("hrv")[len(first):]
        self.assertEqual(len(later), 3)
        self.assertEqual(len(set(self.hist("hrv"))), len(self.hist("hrv")))  # nothing twice
        led = stubs.run(self.mgr.ledger())
        self.assertTrue(led.knows("hrv", day.isoformat()))
        self.assertFalse(led.is_done("hrv", day.isoformat()))
        self.api.sync = "t3"
        self.cycle(c)
        self.assertEqual(len(self.hist("hrv")), len(first) + 3)

    def test_no_hrv_requests_without_an_enabled_history_sensor_and_no_hourly_statistic(self):
        self.hrv_on = False
        self.cycle(self.make())
        self.assertEqual(self.api.n("hrv"), 0)
        self.hrv_on = True
        self.api.calls.clear()
        self.cycle(self.make(hourly=True, auto=True))
        self.assertGreater(self.api.n("hrv"), 0)
        self.assertEqual([r for r in stubs.RECORDED if "hrv" in str(r)], [])


class LatestValue(LiveBase):
    """The history sensor shows the newest point of the forward path (state_writes counts rows)."""

    def sensor(self, series="heart_rate"):
        key = hs.HISTORY_KEYS[series]
        sensor = sn.GarminHistorySensor(self.entry, key, "bpm")
        sensor.hass = self.hass
        stubs.run(sensor.async_added_to_hass())
        return sensor

    def test_forward_path_sets_value_and_time_and_writes_a_row_only_for_a_newer_point(self):
        c = self.make()
        sensor = self.sensor()
        self.assertIsNone(sensor.native_value)
        self.cycle(c)
        newest = max(ms(2026, 10, 24, 12, 10), ms(2026, 10, 24, 11, 50))
        self.assertEqual(sensor.native_value, 99.0)
        self.assertEqual(sensor.extra_state_attributes["measured_at"], "2026-10-24T12:10:00+00:00")
        self.assertEqual(sensor._measured_ms, newest)
        rows = sensor.state_writes
        self.api.sync = "t2"
        self.cycle(c)  # nothing new
        self.assertEqual(sensor.state_writes, rows)
        self.api.hr[tic.TODAY] = hr_payload([(ms(2026, 10, 24, 12, 10), 99), (ms(2026, 10, 24, 12, 40), 77)])
        self.api.sync = "t3"
        self.cycle(c)
        self.assertEqual((sensor.native_value, sensor.state_writes), (77.0, rows + 1))

    def test_late_older_point_does_not_move_the_state(self):
        c = self.make()
        sensor = self.sensor()
        self.cycle(c)
        rows = sensor.state_writes
        self.api.hr[tic.TODAY] = hr_payload([(ms(2026, 10, 24, 12, 10), 99), (ms(2026, 10, 24, 3, 0), 55)])
        self.api.sync = "t2"
        self.cycle(c)
        self.assertEqual((sensor.native_value, sensor.state_writes), (99.0, rows))

    def test_old_days_never_touch_the_state(self):
        api = BackfillApi()
        day = D - timedelta(days=2)
        api.hr[day] = hr_payload([(ms(day.year, day.month, day.day, 8, 0), 60)])
        mgr, entry = make_manager(self, api)
        self.entry, self.hass = entry, mgr.hass
        sensor = self.sensor()
        self.target_errors = {"spo2": "history_sensor_disabled", "body_battery": "history_sensor_disabled"}
        stubs.run(mgr.run_backfill(api))  # initial load
        self.assertEqual(self.written[0][0], "heart_rate")
        self.assertIsNone(sensor.native_value)
        led = stubs.run(mgr.ledger())
        res = stubs.run(hs.append_points(mgr.hass, entry, led, "heart_rate", day - timedelta(days=1),
                                         [(ms(2026, 10, 21, 8, 0), 58.0)]))  # a service run for an old day
        self.assertEqual((res.written, sensor.native_value), (1, None))

    def test_progress_updates_keep_the_value(self):
        c = self.make()
        sensor = self.sensor()
        self.cycle(c)
        self.mgr.progress["heart_rate"] = {"history_backfilled_until": "2026-10-20"}
        self.mgr.listeners["heart_rate"]()
        self.assertEqual(sensor.native_value, 99.0)
        self.assertEqual(sensor.extra_state_attributes["history_backfilled_until"], "2026-10-20")
        self.assertIn("measured_at", sensor.extra_state_attributes)

    def test_first_run_with_a_filled_ledger_shows_the_newest_point(self):
        c = self.make()
        self.cycle(c)
        saved = stubs.Store.instances[-1].saved[-1]
        stubs.Store.preset = saved  # reload: the ledger already holds the points
        c2 = self.make()
        sensor = self.sensor()
        self.api.sync = "t9"
        self.written.clear()
        self.cycle(c2)
        self.assertEqual(self.written, [])  # nothing written again
        self.assertEqual(sensor.native_value, 99.0)

    def test_restore_after_restart(self):
        self.make()
        sensor = sn.GarminHistorySensor(self.entry, "heart_rate_history", "bpm")
        sensor.hass = self.hass
        sensor._stored = SimpleNamespace(native_value=71.0)
        sensor._stored_state = SimpleNamespace(state="71.0", attributes={"measured_at": "2026-10-24T08:00:00+00:00"})
        stubs.run(sensor.async_added_to_hass())
        self.assertEqual(sensor.native_value, 71.0)
        self.assertEqual(sensor.extra_state_attributes["measured_at"], "2026-10-24T08:00:00+00:00")
        sensor.show_latest(ms(2026, 10, 24, 7, 0), 50.0)  # older than the restored point
        self.assertEqual(sensor.native_value, 71.0)
        empty = sn.GarminHistorySensor(self.entry, "spo2_history", "%")
        empty.hass = self.hass
        stubs.run(empty.async_added_to_hass())
        self.assertIsNone(empty.native_value)

    def test_value_published_before_sensor_exists(self):
        self.make()
        manager = sn.manager_for(self.hass, self.entry)
        manager.publish_latest("heart_rate", [(ms(2026, 10, 24, 7, 0), 60.0), (ms(2026, 10, 24, 8, 0), 72.0)])
        sensor = sn.GarminHistorySensor(self.entry, "heart_rate_history", "bpm")
        sensor.hass = self.hass
        stubs.run(sensor.async_added_to_hass())
        self.assertEqual(sensor.native_value, 72.0)
        self.assertEqual(sensor.extra_state_attributes["measured_at"], "2026-10-24T08:00:00+00:00")


TODAY_ISO = "2026-10-24"

if __name__ == "__main__":
    unittest.main()
