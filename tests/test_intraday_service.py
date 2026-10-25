"""Service garmin_personal.backfill_intraday: range, hourly rows, partial results, lock (invented numbers)."""

import asyncio
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
sv = sys.modules["gp_full.services"]
api_mod = sys.modules["gp_full.api"]
DOMAIN = "garmin_personal"
SVC_ERR = stubs.ServiceValidationError
HA_ERR = stubs.HomeAssistantError
TODAY = date(2026, 10, 24)
NOW = datetime(2026, 10, 24, 12, 30, tzinfo=UTC)


class FakeRuntime:
    def __init__(self, api):
        self.api = api


class FakeApi:
    """Answers per day; ``fail`` maps (series, day) to an exception, ``gate`` blocks heart rate."""

    def __init__(self):
        self.calls = []
        self.hr, self.bb, self.spo2 = {}, {}, {}
        self.fail = {}
        self.gate = None

    def _answer(self, name, store, day):
        self.calls.append((name, day))
        exc = self.fail.get((name, day))
        if exc:
            raise exc
        return store.get(day)

    async def get_heart_rate(self, day):
        if self.gate is not None:
            await self.gate.wait()
        return self._answer("heart_rate", self.hr, day)

    async def get_body_battery(self, start, end, chunks=None):
        assert start == end
        return self._answer("body_battery", self.bb, start)

    async def get_spo2(self, day):
        return self._answer("spo2", self.spo2, day)


class Base(unittest.TestCase):
    def setUp(self):
        stubs.RECORDED.clear()
        self.api = FakeApi()
        self.entry = stubs.FakeEntry(entry_id="E1", title="Alex", runtime_data=FakeRuntime(self.api))
        self.hass = stubs.FakeHass()
        self.hass.config_entries.entries = [self.entry]
        sv.async_register_services(self.hass)
        for name, value in (("now", lambda: NOW), ("utcnow", lambda: NOW)):
            orig = getattr(sv.dt_util, name)
            setattr(sv.dt_util, name, value)
            self.addCleanup(setattr, sv.dt_util, name, orig)

    def call(self, data=None):
        handler = self.hass.services.registered[(DOMAIN, "backfill_intraday")]["handler"]
        return stubs.run(handler(stubs.FakeCall(data)))

    def rows(self, name):
        out = {}
        for _, meta, rows in stubs.RECORDED:
            if meta.kw["statistic_id"].endswith("_" + name):
                for r in rows:
                    out[r.start] = (r.min, r.max, r.mean)
        return out

    def metas(self):
        return {m.kw["statistic_id"]: m.kw for _, m, _ in stubs.RECORDED}


def utc(*args):
    return datetime(*args, tzinfo=UTC)


class Flow(Base):
    def test_writes_hourly_rows_for_all_three_series(self):
        d = date(2026, 10, 23)
        self.api.hr[d] = hr_payload([(ms(2026, 10, 23, 8, 0), 60), (ms(2026, 10, 23, 8, 2), 70), (ms(2026, 10, 23, 8, 4), 80),
                                     (ms(2026, 10, 23, 10, 0), 0), (ms(2026, 10, 23, 11, 0), 55)])
        self.api.bb[d] = bb_payload([(ms(2026, 10, 23, 8, 10), 90), (ms(2026, 10, 23, 8, 40), 80)])
        self.api.spo2[d] = spo2_payload([(ms(2026, 10, 23, 8, 0), 96)])
        out = self.call({"start_date": d, "end_date": d})
        self.assertEqual(self.rows("heart_rate_hourly"),
                         {utc(2026, 10, 23, 8): (60.0, 80.0, 70.0), utc(2026, 10, 23, 11): (55.0, 55.0, 55.0)})
        self.assertEqual(self.rows("body_battery_hourly"), {utc(2026, 10, 23, 8): (80.0, 90.0, 85.0)})
        self.assertEqual(self.rows("spo2_hourly"), {utc(2026, 10, 23, 8): (96.0, 96.0, 96.0)})
        self.assertIs(out["complete"], True)
        self.assertEqual((out["heart_rate_hours"], out["body_battery_hours"], out["spo2_hours"]), (2, 1, 1))
        self.assertEqual((out["statistic_series"], out["statistic_rows"], out["days_completed"]), (3, 4, 1))
        self.assertEqual(out["days_with_data"], 1)
        self.assertNotIn("unknown_format", out)

    def test_statistic_ids_names_and_units(self):
        d = date(2026, 10, 23)
        self.api.hr[d] = hr_payload([(ms(2026, 10, 23, 8, 0), 60)])
        self.api.bb[d] = bb_payload([(ms(2026, 10, 23, 8, 0), 60)])
        self.api.spo2[d] = spo2_payload([(ms(2026, 10, 23, 8, 0), 96)])
        self.call({"start_date": d, "end_date": d})
        metas = self.metas()
        self.assertEqual(set(metas), {"garmin_personal:e1_heart_rate_hourly", "garmin_personal:e1_body_battery_hourly",
                                      "garmin_personal:e1_spo2_hourly"})
        hr = metas["garmin_personal:e1_heart_rate_hourly"]
        self.assertEqual((hr["unit_of_measurement"], hr["has_sum"], hr["source"]), ("bpm", False, DOMAIN))
        self.assertEqual(hr["name"], "Alex heart rate (hourly)")
        self.assertEqual(metas["garmin_personal:e1_spo2_hourly"]["unit_of_measurement"], "%")
        self.assertIn("mean_type", hr)
        import re  # Home Assistant's rule for external statistic ids
        valid = re.compile(r"^(?!.+__)(?!_)[\da-z_]+(?<!_):(?!_)[\da-z_]+(?<!_)$")
        self.assertTrue(all(valid.match(i) for i in metas), metas)
        rows = [r for _, m, rows in stubs.RECORDED for r in rows]
        self.assertTrue(all(r.start.minute == 0 and r.start.second == 0 and r.start.tzinfo is not None for r in rows))

    def test_one_request_per_day_and_series(self):
        self.call({"days": 3})
        self.assertEqual(len(self.api.calls), 9)
        self.assertEqual(sorted({day for _, day in self.api.calls}),
                         [date(2026, 10, 22), date(2026, 10, 23), date(2026, 10, 24)])

    def test_default_range_is_seven_days_ending_today(self):
        out = self.call()
        self.assertEqual((out["start_date"], out["end_date"]), ("2026-10-18", "2026-10-24"))
        self.assertIs(out["partial_day_included"], True)

    def test_running_hour_of_today_is_not_written(self):
        self.api.hr[TODAY] = hr_payload([(ms(2026, 10, 24, 11, 5), 60), (ms(2026, 10, 24, 12, 5), 99)])
        self.call({"days": 1})
        self.assertEqual(list(self.rows("heart_rate_hourly")), [utc(2026, 10, 24, 11)])

    def test_nothing_written_without_data_and_no_gaps_filled(self):
        d = date(2026, 10, 23)
        self.api.hr[d] = hr_payload([(ms(2026, 10, 23, 2, 5), 50), (ms(2026, 10, 23, 6, 5), 52)])
        out = self.call({"start_date": d, "end_date": d})
        self.assertEqual(list(self.rows("heart_rate_hourly")), [utc(2026, 10, 23, 2), utc(2026, 10, 23, 6)])
        self.assertEqual(out["statistic_series"], 1)
        self.assertEqual(self.rows("spo2_hourly"), {})

    def test_repeating_overwrites_the_same_hours(self):
        d = date(2026, 10, 23)
        self.api.hr[d] = hr_payload([(ms(2026, 10, 23, 8, 0), 60)])
        self.call({"start_date": d, "end_date": d})
        self.api.hr[d] = hr_payload([(ms(2026, 10, 23, 8, 0), 60), (ms(2026, 10, 23, 8, 30), 70)])
        self.call({"start_date": d, "end_date": d})
        runs = [rows for _, m, rows in stubs.RECORDED if m.kw["statistic_id"].endswith("heart_rate_hourly")]
        self.assertEqual([[r.start for r in rows] for rows in runs], [[utc(2026, 10, 23, 8)]] * 2)
        self.assertEqual(runs[1][0].mean, 65.0)

    def test_hour_over_a_day_boundary_is_averaged_from_both_days(self):
        # Two answers each hold one half of the same UTC hour (as in a +05:30 zone).
        self.api.hr[date(2026, 10, 22)] = hr_payload([(ms(2026, 10, 22, 18, 10), 60)])
        self.api.hr[date(2026, 10, 23)] = hr_payload([(ms(2026, 10, 22, 18, 40), 80)])
        self.call({"start_date": date(2026, 10, 22), "end_date": date(2026, 10, 23)})
        self.assertEqual(self.rows("heart_rate_hourly"), {utc(2026, 10, 22, 18): (60.0, 80.0, 70.0)})

    def test_hour_split_across_a_flush_is_not_cut(self):
        first = date(2026, 9, 14)
        self.api.hr[first + timedelta(days=30)] = hr_payload([(ms(2026, 10, 14, 23, 10), 60)])  # 31st day
        self.api.hr[first + timedelta(days=31)] = hr_payload([(ms(2026, 10, 14, 23, 40), 80)])  # 32nd day
        self.call({"start_date": first, "end_date": date(2026, 10, 23)})
        self.assertEqual(self.rows("heart_rate_hourly"), {utc(2026, 10, 14, 23): (60.0, 80.0, 70.0)})
        written = [r.start for _, m, rows in stubs.RECORDED if m.kw["statistic_id"].endswith("heart_rate_hourly") for r in rows]
        self.assertEqual(written.count(utc(2026, 10, 14, 23)), 1)  # never written as a half hour first

    def test_flushes_in_chunks_but_one_row_per_hour(self):
        for n in range(40):
            d = date(2026, 9, 14) + timedelta(days=n)
            self.api.hr[d] = hr_payload([(ms(d.year, d.month, d.day, 8, 0), 60 + n)])
        out = self.call({"start_date": date(2026, 9, 14), "end_date": date(2026, 10, 23)})
        self.assertEqual(out["heart_rate_hours"], 40)
        starts = [r.start for _, m, rows in stubs.RECORDED if m.kw["statistic_id"].endswith("heart_rate_hourly") for r in rows]
        self.assertEqual(len(starts), len(set(starts)))
        self.assertGreater(len([1 for _, m, _ in stubs.RECORDED if m.kw["statistic_id"].endswith("heart_rate_hourly")]), 1)

    def test_unknown_format_is_reported_not_raised(self):
        d = date(2026, 10, 23)
        self.api.hr[d] = {"something": "else"}
        self.api.spo2[d] = spo2_payload([(ms(2026, 10, 23, 8, 0), 96)])
        out = self.call({"start_date": d, "end_date": d})
        self.assertEqual(out["unknown_format"], ["heart_rate"])
        self.assertIs(out["complete"], True)
        self.assertEqual(self.rows("heart_rate_hourly"), {})
        self.assertEqual(len(self.rows("spo2_hourly")), 1)


class Limits(Base):
    def test_366_days_allowed_367_not(self):
        out = self.call({"days": 366})
        self.assertEqual(out["days_completed"], 366)
        with self.assertRaises(SVC_ERR) as ctx:
            self.call({"start_date": date(2025, 10, 23), "end_date": TODAY})  # 367 days
        self.assertEqual(ctx.exception.translation_key, "date_range_too_long")
        self.assertEqual(ctx.exception.translation_placeholders["max_days"], "366")

    def test_schema_limits_and_default(self):
        days = sv.INTRADAY_SCHEMA.keys()["days"]
        self.assertEqual(days.default, 7)
        rng = next(v for v in sv.INTRADAY_SCHEMA.schema[days].args if hasattr(v, "kwargs") and "max" in v.kwargs)
        self.assertEqual((rng.kwargs["min"], rng.kwargs["max"]), (1, 366))

    def test_reversed_range(self):
        with self.assertRaises(SVC_ERR) as ctx:
            self.call({"start_date": TODAY, "end_date": date(2026, 10, 1)})
        self.assertEqual(ctx.exception.translation_key, "invalid_date_range")
        self.assertEqual(self.api.calls, [])

    def test_future_end_is_clamped_to_today(self):
        out = self.call({"days": 1, "end_date": date(2027, 1, 1)})
        self.assertEqual(out["end_date"], "2026-10-24")

    def test_unknown_account(self):
        with self.assertRaises(SVC_ERR) as ctx:
            self.call({"config_entry_id": "nope"})
        self.assertEqual(ctx.exception.translation_key, "entry_unknown")


class Failures(Base):
    def test_rate_limit_stops_with_partial_result_and_keeps_earlier_days(self):
        for d in (date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)):
            self.api.hr[d] = hr_payload([(ms(d.year, d.month, d.day, 8, 0), 60)])
        self.api.fail[("heart_rate", date(2026, 10, 23))] = api_mod.GarminRateLimitError("429")
        out = self.call({"start_date": date(2026, 10, 21), "end_date": date(2026, 10, 23)})
        self.assertIs(out["complete"], False)
        self.assertEqual(out["last_completed_day"], "2026-10-22")
        self.assertIn("429", out["error"])
        self.assertEqual(out["days_completed"], 2)
        self.assertEqual(len(self.rows("heart_rate_hourly")), 2)
        # no request after the stop
        self.assertEqual(self.api.calls[-1], ("heart_rate", date(2026, 10, 23)))

    def test_first_request_fails_raises(self):
        self.api.fail[("heart_rate", date(2026, 10, 22))] = api_mod.GarminRateLimitError("429")
        with self.assertRaises(HA_ERR) as ctx:
            self.call({"start_date": date(2026, 10, 22), "end_date": date(2026, 10, 23)})
        self.assertEqual(ctx.exception.translation_key, "garmin_request_failed")
        self.assertEqual(stubs.RECORDED, [])

    def test_auth_error_stops(self):
        self.api.fail[("spo2", date(2026, 10, 23))] = api_mod.GarminAuthError("bad key")
        d = date(2026, 10, 22)
        self.api.hr[d] = hr_payload([(ms(2026, 10, 22, 8, 0), 60)])
        out = self.call({"start_date": d, "end_date": date(2026, 10, 23)})
        self.assertIs(out["complete"], False)
        self.assertEqual(out["last_completed_day"], "2026-10-22")

    def test_other_error_is_reported_and_the_run_continues(self):
        d = date(2026, 10, 22)
        self.api.fail[("body_battery", d)] = api_mod.GarminApiError("boom", 500)
        self.api.hr[d] = hr_payload([(ms(2026, 10, 22, 8, 0), 60)])
        self.api.bb[date(2026, 10, 23)] = bb_payload([(ms(2026, 10, 23, 8, 0), 50)])
        out = self.call({"start_date": d, "end_date": date(2026, 10, 23)})
        self.assertIs(out["complete"], True)
        self.assertIn("boom", out["body_battery_error"])
        self.assertEqual(out["body_battery_days_failed"], 1)
        self.assertEqual(len(self.rows("heart_rate_hourly")), 1)
        self.assertEqual(len(self.rows("body_battery_hourly")), 1)

    def test_error_releases_lock(self):
        self.api.fail[("heart_rate", TODAY)] = api_mod.GarminApiError("x", 500)
        self.call({"days": 1})
        self.api.fail.clear()
        self.call({"days": 1})


class Lock(Base):
    def test_parallel_runs_for_one_account_are_refused_and_share_the_backfill_lock(self):
        handler = self.hass.services.registered[(DOMAIN, "backfill_intraday")]["handler"]

        async def scenario():
            self.api.gate = asyncio.Event()
            first = asyncio.ensure_future(handler(stubs.FakeCall({"days": 1})))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            with self.assertRaises(SVC_ERR) as ctx:
                await handler(stubs.FakeCall({"days": 1}))
            self.assertEqual(ctx.exception.translation_key, "backfill_running")
            other = self.hass.services.registered[(DOMAIN, "backfill_statistics")]["handler"]
            with self.assertRaises(SVC_ERR):
                await other(stubs.FakeCall({"days": 1}))
            self.api.gate.set()
            await first
            await handler(stubs.FakeCall({"days": 1}))

        stubs.run(scenario())


class Privacy(Base):
    def test_values_are_not_logged(self):
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)
        d = date(2026, 10, 23)
        self.api.hr[d] = hr_payload([(ms(2026, 10, 23, 8, 0), 4711)])
        self.api.spo2[d] = {"weird": 4711}
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger("gp_full").debug("start")
            self.call({"start_date": d, "end_date": d})
        self.assertNotIn("4711", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
