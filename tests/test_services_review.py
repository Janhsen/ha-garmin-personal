"""services.py nach dem Review: Konto-Auswahl, Backfill-Grenzen/Fenster/Sperre, Deduplizierung,
Nullwerte, Rueckgabewerte, unit_class, Download-Pfade, Datenschutz im Log (nur erfundene Beispielzahlen)."""

import asyncio
import itertools
import logging
import os
import sys
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402

gp = stubs.load_full()
sv = sys.modules["gp_full.services"]
api_mod = sys.modules["gp_full.api"]
models = sys.modules["homeassistant.components.recorder.models"]
DOMAIN = "garmin_personal"
SVC_ERR = stubs.ServiceValidationError
HA_ERR = stubs.HomeAssistantError
TODAY = date(2026, 10, 24)
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


class FakeRuntime:
    def __init__(self, api):
        self.api = api


class FakeApi:
    def __init__(self):
        self.calls = []
        self.error_at = {}  # Aufrufnummer (1-basiert) der Tageszusammenfassungen -> Ausnahme
        self.summaries = []
        self.per_window = None  # optional: Funktion (start, end) -> Liste
        self.sleeps, self.hrv = [], []
        self.weights = {"dailyWeightSummaries": []}
        self.sleep_error = None
        self.gate = None
        self.zip = b"PK\x03\x04data"
        self.fetch_result = {"x": 1}

    async def fetch(self, endpoint, **kw):
        self.calls.append(("fetch", endpoint, kw))
        return self.fetch_result

    async def get_daily_summaries(self, start, end):
        self.calls.append(("summaries", start, end))
        if self.gate is not None:
            await self.gate.wait()
        exc = self.error_at.get(len([c for c in self.calls if c[0] == "summaries"]))
        if exc:
            raise exc
        return self.per_window(start, end) if self.per_window else self.summaries

    async def get_sleep_summaries(self, start, end):
        if self.sleep_error:
            raise self.sleep_error
        return self.sleeps

    async def get_hrv_summaries(self, start, end):
        return self.hrv

    async def get_weight_range(self, start, end):
        return self.weights

    async def download_activity_zip(self, activity_id):
        self.calls.append(("download", activity_id))
        return self.zip


def loaded(entry_id="E1", api=None, title="Alex"):
    return stubs.FakeEntry(entry_id=entry_id, title=title, runtime_data=FakeRuntime(api or FakeApi()))


class Base(unittest.TestCase):
    def setUp(self):
        stubs.RECORDED.clear()
        self.api = FakeApi()
        self.entry = loaded(api=self.api)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.config = stubs.FakeConfig(self.root, (os.path.join(self.root, "media"),))
        self.hass = stubs.FakeHass(self.config)
        self.hass.config_entries.entries = [self.entry]
        sv.async_register_services(self.hass)
        orig = sv.dt_util.now
        sv.dt_util.now = lambda: NOW
        self.addCleanup(setattr, sv.dt_util, "now", orig)

    def call(self, name, data=None):
        handler = self.hass.services.registered[(DOMAIN, name)]["handler"]
        return stubs.run(handler(stubs.FakeCall(data)))

    def series(self):
        out = {}
        for _, meta, rows in stubs.RECORDED:
            out.setdefault(meta.kw["statistic_id"].split(":", 1)[1].split("_", 1)[1], []).extend(rows)
        return out


class EntryChoice(unittest.TestCase):
    def hass(self, *entries):
        h = stubs.FakeHass()
        h.config_entries.entries = list(entries)
        return h

    def test_several_entries_list_titles_in_error(self):
        with self.assertRaises(SVC_ERR) as ctx:
            sv._get_entry(self.hass(loaded("A", title="Alex"), loaded("B", title="Sam")), stubs.FakeCall())
        self.assertEqual(ctx.exception.translation_domain, DOMAIN)
        listing = ctx.exception.translation_placeholders["entries"]
        self.assertIn("Alex (A)", listing)
        self.assertIn("Sam (B)", listing)

    def test_second_entry_not_loaded_is_not_a_silent_fallback(self):
        broken = stubs.FakeEntry(entry_id="B", title="Sam")
        with self.assertRaises(SVC_ERR) as ctx:
            sv._get_entry(self.hass(loaded("A"), broken), stubs.FakeCall())
        self.assertEqual(ctx.exception.translation_key, "entry_required")

    def test_state_must_be_loaded(self):
        e = loaded("A")
        e.state = stubs.ConfigEntryState.SETUP_RETRY
        with self.assertRaises(SVC_ERR) as ctx:
            sv._get_entry(self.hass(e), stubs.FakeCall({"config_entry_id": "A"}))
        self.assertEqual(ctx.exception.translation_key, "entry_not_loaded")
        self.assertEqual(ctx.exception.translation_placeholders, {"title": "Alex"})

    def test_every_error_is_translated(self):
        """Keine hartkodierten Klartexte: jeder Fehler hat Domain und Schluessel."""
        for exc in (sv._invalid("x", a=1), sv._failed("y", b=2)):
            self.assertEqual(exc.translation_domain, DOMAIN)
            self.assertTrue(exc.translation_key)
            self.assertEqual(exc.args, ())
        self.assertEqual(sv._invalid("x", a=1).translation_placeholders, {"a": "1"})


class FilterBooleans(unittest.TestCase):
    def test_string_false_is_false(self):
        self.assertIs(sv._filters({"favorite": "false"})["favorite"], False)
        self.assertIs(sv._filters({"favorite": "true"})["favorite"], True)
        self.assertIs(sv._filters({"favorite": "0", "exclude_children": "off"})["exclude_children"], False)

    def test_other_filters_untouched_and_none_kept(self):
        out = sv._filters({"activity_type": "running", "favorite": None, "min_distance": 1000})
        self.assertEqual(out, {"activity_type": "running", "favorite": None, "min_distance": 1000})

    def test_garbage_boolean_and_non_mapping_rejected(self):
        for bad in ({"favorite": "maybe"}, [("favorite", 1)], "favorite"):
            with self.assertRaises(sv.vol.Invalid):
                sv._filters(bad)

    def test_schemas_use_validator(self):
        for name in ("fetch", "search_activities"):
            hass = stubs.FakeHass()
            sv.async_register_services(hass)
            keys = hass.services.registered[(DOMAIN, name)]["schema"].schema
            validator = next(v for k, v in keys.items() if str(k.schema) == "filters")
            self.assertIs(validator, sv._filters)


class Fetch(Base):
    def test_today_follows_ha_clock_not_process_clock(self):
        self.call("fetch", {"endpoint": "steps", "limit": 20})
        self.assertEqual(self.api.calls[0][2]["today"], TODAY)

    def test_range_start_too_far_back(self):
        with self.assertRaises(SVC_ERR) as ctx:
            self.call("fetch", {"endpoint": "steps", "limit": 20, "start_date": date(2000, 1, 1)})
        self.assertEqual(ctx.exception.translation_key, "date_range_too_long")
        self.assertEqual(self.api.calls, [])

    def test_range_reversed(self):
        with self.assertRaises(SVC_ERR) as ctx:
            self.call("fetch", {"endpoint": "steps", "limit": 20, "start_date": date(2026, 10, 5),
                                "end_date": date(2026, 10, 1)})
        self.assertEqual(ctx.exception.translation_key, "invalid_date_range")

    def test_sensitive_endpoints_leave_no_data_in_log(self):
        self.api.fetch_result = {"entries": [{"note": "GEHEIM-4711"}]}
        for endpoint in ("nutrition", "menstrual_day", "menstrual_summary"):
            with self.assertLogs(sv._LOGGER, level=logging.DEBUG) as logs:
                out = self.call("fetch", {"endpoint": endpoint, "limit": 20})
            self.assertEqual(out["data"], self.api.fetch_result)
            self.assertNotIn("GEHEIM-4711", "\n".join(logs.output))
        self.assertEqual(stubs.RECORDED, [])  # nichts davon wird als Statistik abgelegt


class BackfillRange(Base):
    def test_default_excludes_today(self):
        out = self.call("backfill_statistics", {"days": 3})
        _, start, end = self.api.calls[0]
        self.assertEqual((start, end), (date(2026, 10, 21), date(2026, 10, 23)))
        self.assertIs(out["partial_day_included"], False)
        self.assertEqual((out["start_date"], out["end_date"]), ("2026-10-21", "2026-10-23"))

    def test_explicit_today_is_flagged(self):
        out = self.call("backfill_statistics", {"days": 2, "end_date": TODAY})
        self.assertEqual(self.api.calls[0][1:], (date(2026, 10, 23), TODAY))
        self.assertIs(out["partial_day_included"], True)

    def test_future_end_is_clamped_to_today(self):
        out = self.call("backfill_statistics", {"days": 1, "end_date": date(2027, 1, 1)})
        self.assertEqual(self.api.calls[0][2], TODAY)
        self.assertIs(out["partial_day_included"], True)

    def test_start_today_without_end_is_an_error(self):
        with self.assertRaises(SVC_ERR) as ctx:
            self.call("backfill_statistics", {"days": 1, "start_date": TODAY})
        self.assertEqual(ctx.exception.translation_key, "invalid_date_range")

    def test_start_date_is_bounded_too(self):
        with self.assertRaises(SVC_ERR) as ctx:
            self.call("backfill_statistics", {"days": 1, "start_date": date(1999, 1, 1)})
        self.assertEqual(ctx.exception.translation_key, "date_range_too_long")
        self.assertEqual(ctx.exception.translation_placeholders["max_days"], "3650")
        self.assertEqual(self.api.calls, [])

    def test_exactly_max_days_is_allowed(self):
        self.call("backfill_statistics", {"days": 3650, "end_date": date(2026, 10, 23)})
        self.assertTrue(self.api.calls)

    def test_long_range_runs_in_windows(self):
        self.call("backfill_statistics", {"days": 70})
        windows = [c[1:] for c in self.api.calls if c[0] == "summaries"]
        self.assertEqual(len(windows), 3)
        self.assertEqual(windows[0][0], date(2026, 8, 15))
        self.assertEqual(windows[-1][1], date(2026, 10, 23))
        for (_, a_end), (b_start, _) in itertools.pairwise(windows):
            self.assertEqual((b_start - a_end).days, 1)  # lueckenlos, ohne Ueberlapp


class BackfillPartial(Base):
    def day(self, offset, steps):
        d = date.fromordinal(date(2026, 10, 23).toordinal() - offset)
        return {"calendarDate": d.isoformat(), "totalSteps": steps}

    def test_failure_in_later_window_keeps_earlier_windows(self):
        self.api.summaries = [{"calendarDate": "2026-09-01", "totalSteps": 100}]
        self.api.error_at = {2: api_mod.GarminApiError("boom", 500)}
        out = self.call("backfill_statistics", {"days": 70})
        self.assertIs(out["complete"], False)
        self.assertIn("boom", out["error"])
        self.assertEqual(out["last_completed_day"], "2026-09-14")
        self.assertEqual(out["days_imported"], 1)
        self.assertEqual(len([c for c in self.api.calls if c[0] == "summaries"]), 2)  # kein dritter Versuch
        self.assertIn("steps", self.series())

    def test_failure_in_first_window_raises(self):
        self.api.error_at = {1: api_mod.GarminApiError("boom", 500)}
        with self.assertRaises(HA_ERR) as ctx:
            self.call("backfill_statistics", {"days": 70})
        self.assertEqual(ctx.exception.translation_key, "garmin_request_failed")
        self.assertEqual(stubs.RECORDED, [])

    def test_rate_limit_in_secondary_endpoint_stops_cleanly(self):
        self.api.summaries = [{"calendarDate": "2026-10-01", "totalSteps": 5}]
        self.api.sleep_error = api_mod.GarminRateLimitError("429")
        out = self.call("backfill_statistics", {"days": 70})
        self.assertIs(out["complete"], False)
        self.assertEqual(len([c for c in self.api.calls if c[0] == "summaries"]), 1)

    def test_other_secondary_error_is_reported_and_run_continues(self):
        self.api.sleep_error = api_mod.GarminApiError("x", 500)
        out = self.call("backfill_statistics", {"days": 70})
        self.assertIs(out["complete"], True)
        self.assertIn("sleep_error", out)
        self.assertEqual(len([c for c in self.api.calls if c[0] == "summaries"]), 3)


class BackfillLock(Base):
    def test_parallel_backfill_of_same_entry_is_refused(self):
        handler = self.hass.services.registered[(DOMAIN, "backfill_statistics")]["handler"]

        async def scenario():
            self.api.gate = asyncio.Event()
            first = asyncio.ensure_future(handler(stubs.FakeCall({"days": 1})))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            with self.assertRaises(SVC_ERR) as ctx:
                await handler(stubs.FakeCall({"days": 1}))
            self.assertEqual(ctx.exception.translation_key, "backfill_running")
            self.api.gate.set()
            await first
            await handler(stubs.FakeCall({"days": 1}))  # danach wieder frei

        stubs.run(scenario())

    def test_error_releases_lock(self):
        self.api.error_at = {1: api_mod.GarminApiError("x", 500)}
        with self.assertRaises(HA_ERR):
            self.call("backfill_statistics", {"days": 1})
        self.api.error_at = {}
        self.call("backfill_statistics", {"days": 1})


class Dedupe(Base):
    def run_days(self, entries, third_party=False):
        self.api.summaries = entries
        return self.call("backfill_statistics", {"days": 5, "include_third_party_steps": third_party})

    def steps(self):
        return [r.mean for r in self.series().get("steps", [])]

    def test_garmin_wins_over_foreign_source_in_any_order(self):
        garmin = {"calendarDate": "2026-10-20", "source": "GARMIN", "totalSteps": 5100}
        foreign = {"calendarDate": "2026-10-20", "source": "fitbit", "totalSteps": 6800}
        for order in ((garmin, foreign), (foreign, garmin)):
            stubs.RECORDED.clear()
            out = self.run_days(list(order), third_party=True)
            self.assertEqual(self.steps(), [5100.0])
            self.assertEqual(out["days_imported"], 1)
            self.assertEqual(out["days_imported_third_party_steps"], 0)

    def test_sourceless_counts_as_garmin(self):
        self.run_days([{"calendarDate": "2026-10-20", "source": "fitbit", "totalSteps": 7},
                       {"calendarDate": "2026-10-20", "totalSteps": 5}], third_party=True)
        self.assertEqual(self.steps(), [5.0])

    def test_foreign_source_only_for_days_without_usable_garmin(self):
        out = self.run_days([
            {"calendarDate": "2026-10-20", "source": "garmin", "totalSteps": 0},  # Platzhalter
            {"calendarDate": "2026-10-20", "source": "fitbit", "totalSteps": 6800},
        ], third_party=True)
        self.assertEqual(self.steps(), [6800.0])
        self.assertEqual(out["days_imported_third_party_steps"], 1)
        self.assertEqual(out["days_imported"], 0)
        self.assertEqual(out["days_skipped_placeholder"], 0)

    def test_one_row_per_hour(self):
        self.run_days([{"calendarDate": "2026-10-20", "totalSteps": 1}, {"calendarDate": "2026-10-20", "totalSteps": 2}])
        starts = [r.start for r in self.series()["steps"]]
        self.assertEqual(len(starts), len(set(starts)))

    def test_sleep_duplicates_do_not_make_two_rows(self):
        self.api.sleeps = [{"calendarDate": "2026-10-20", "sleepTimeSeconds": 100},
                           {"calendarDate": "2026-10-20", "sleepTimeSeconds": 200}]
        self.call("backfill_statistics", {"days": 5})
        self.assertEqual([r.mean for r in self.series()["sleep_duration"]], [100.0])

    def test_skip_counts_are_per_day(self):
        out = self.run_days([
            {"calendarDate": "2026-10-20", "source": "fitbit", "totalSteps": 1},
            {"calendarDate": "2026-10-20", "source": "fitbit", "totalSteps": 2},
            {"calendarDate": "2026-10-21", "source": "garmin", "totalSteps": 0},
        ])
        self.assertEqual(out["days_skipped_other_source"], 1)
        self.assertEqual(out["days_skipped_placeholder"], 1)


class ZeroValues(Base):
    def test_zero_heart_rate_breathing_stress_are_no_value(self):
        self.api.summaries = [{
            "calendarDate": "2026-10-20", "totalSteps": 4100, "restingHeartRate": 50,
            "minHeartRate": 0, "maxHeartRate": 0, "averageStressLevel": 0, "maxStressLevel": 0,
            "avgWakingRespirationValue": 0, "floorsAscended": 0, "activeKilocalories": 0,
            "moderateIntensityMinutes": 0, "bodyBatteryLowestValue": 0,
        }]
        self.call("backfill_statistics", {"days": 5})
        names = set(self.series())
        for gone in ("min_heart_rate", "max_heart_rate", "stress_average", "stress_max", "respiration_average"):
            self.assertNotIn(gone, names)
        for kept in ("steps", "resting_heart_rate", "floors_ascended", "active_calories",
                     "moderate_intensity_minutes", "body_battery_low"):
            self.assertIn(kept, names)
        self.assertEqual([r.mean for r in self.series()["floors_ascended"]], [0.0])

    def test_zero_resting_heart_rate_is_no_value(self):
        self.api.summaries = [{"calendarDate": "2026-10-20", "totalSteps": 9, "restingHeartRate": 0}]
        self.call("backfill_statistics", {"days": 5})
        self.assertNotIn("resting_heart_rate", self.series())

    def test_negative_still_dropped(self):
        self.api.summaries = [{"calendarDate": "2026-10-20", "totalSteps": 9, "minHeartRate": -1,
                               "averageStressLevel": -1}]
        self.call("backfill_statistics", {"days": 5})
        self.assertEqual(set(self.series()), {"steps"})

    def test_sleep_zero_rules(self):
        self.api.sleeps = [{"calendarDate": "2026-10-20", "sleepTimeSeconds": 25000, "avgHeartRate": 0,
                            "averageRespirationValue": 0, "avgSleepStress": 0, "awakeCount": 0,
                            "awakeSleepSeconds": 0}]
        self.call("backfill_statistics", {"days": 5})
        names = set(self.series())
        self.assertTrue({"sleep_duration", "sleep_awake_count", "sleep_awake"} <= names)
        self.assertFalse({"sleep_heart_rate", "sleep_respiration", "sleep_stress"} & names)


class ReturnValues(Base):
    def test_days_returned_ignores_missing_dates(self):
        self.api.summaries = [{"totalSteps": 1}, {"calendarDate": None, "totalSteps": 2},
                              {"calendarDate": "2026-10-20", "totalSteps": 3},
                              {"calendarDate": "2026-10-20", "totalSteps": 4}, "x"]
        out = self.call("backfill_statistics", {"days": 5})
        self.assertEqual(out["days_returned"], 1)
        self.assertEqual(out["days_imported"], 1)

    def test_days_imported_counts_only_days_with_a_written_row(self):
        self.api.summaries = [{"calendarDate": "2026-10-20", "totalSteps": -5}]  # "verwertbar", aber nichts zu schreiben
        out = self.call("backfill_statistics", {"days": 5})
        self.assertEqual((out["days_returned"], out["days_imported"]), (1, 0))
        self.assertEqual((out["statistic_series"], out["statistic_rows"]), (0, 0))
        self.assertNotIn("statistics", out)

    def test_series_and_rows_are_named_apart(self):
        self.api.summaries = [{"calendarDate": "2026-10-20", "totalSteps": 1, "totalDistanceMeters": 2},
                              {"calendarDate": "2026-10-21", "totalSteps": 3}]
        out = self.call("backfill_statistics", {"days": 5})
        self.assertEqual((out["statistic_series"], out["statistic_rows"]), (2, 3))

    def test_counts_add_up_across_windows(self):
        def per_window(start, end):
            return [{"calendarDate": start.isoformat(), "totalSteps": 10}]

        self.api.per_window = per_window
        out = self.call("backfill_statistics", {"days": 70})
        self.assertEqual((out["days_returned"], out["days_imported"], out["statistic_rows"]), (3, 3, 3))
        self.assertEqual(out["statistic_series"], 1)


class UnitClass(Base):
    def run_all(self):
        self.api.summaries = [{"calendarDate": "2026-10-20", "totalSteps": 1, "totalDistanceMeters": 2,
                               "activeKilocalories": 3, "restingHeartRate": 50}]
        self.api.sleeps = [{"calendarDate": "2026-10-20", "sleepTimeSeconds": 100, "sleepNeed": {"actual": 400}}]
        self.api.weights = {"dailyWeightSummaries": [
            {"summaryDate": "2026-10-20", "latestWeight": {"weight": 80000, "sourceType": "MANUAL", "bodyFat": 20}}]}
        self.call("backfill_statistics", {"days": 5})
        return {m.kw["statistic_id"].split(":", 1)[1].split("_", 1)[1]: m.kw for _, m, _ in stubs.RECORDED}

    def test_not_set_when_recorder_has_no_field(self):
        for kw in self.run_all().values():
            self.assertNotIn("unit_class", kw)

    def test_classes_for_convertible_units(self):
        models.StatisticMetaData.__annotations__["unit_class"] = str
        try:
            meta = self.run_all()
        finally:
            del models.StatisticMetaData.__annotations__["unit_class"]
        self.assertEqual(meta["distance"]["unit_class"], "distance")
        self.assertEqual(meta["weight"]["unit_class"], "mass")
        self.assertEqual(meta["sleep_duration"]["unit_class"], "duration")
        self.assertEqual(meta["sleep_need"]["unit_class"], "duration")
        for name in ("steps", "active_calories", "resting_heart_rate", "body_fat"):
            self.assertIsNone(meta[name]["unit_class"], name)

    def test_statistic_ids_unchanged(self):
        """Bestehende Statistiken duerfen nicht umbenannt werden (Name != Entity-Key an einigen Stellen)."""
        names = set(self.run_all())
        self.assertTrue({"steps", "distance", "sleep_duration", "weight", "body_fat"} <= names)
        self.assertIn("sleep_respiration", sv.SLEEP_FIELDS)
        self.assertIn("hrv_weekly_average", sv.HRV_FIELDS)
        self.assertIn("hrv_5_min_high", sv.HRV_FIELDS)


class Download(Base):
    def setUp(self):
        super().setUp()
        self.media = os.path.join(self.root, "media")
        self.config.media_dirs = {"local": self.media}
        self.executor_jobs = []
        orig = self.hass.async_add_executor_job

        async def spy(func, *args):
            self.executor_jobs.append(getattr(func, "__name__", str(func)))
            return await orig(func, *args)

        self.hass.async_add_executor_job = spy

    def test_default_goes_to_media_folder(self):
        out = self.call("download_activity", {"activity_id": 77})
        expected = os.path.join(self.media, DOMAIN, "activity_77.zip")
        self.assertEqual(out["path"], expected)
        self.assertEqual(Path(expected).read_bytes(), self.api.zip)

    def test_default_follows_configured_media_dir(self):
        other = os.path.join(self.root, "media2")
        self.config.media_dirs = {"local": other}
        self.config.allowed = (other,)
        out = self.call("download_activity", {"activity_id": 5})
        self.assertEqual(out["path"], os.path.join(other, DOMAIN, "activity_5.zip"))

    def test_allow_list_check_runs_in_executor(self):
        self.call("download_activity", {"activity_id": 1})
        self.assertIn("resolve", self.executor_jobs)

    def test_error_names_the_folder_to_allow(self):
        self.config.allowed = ()
        with self.assertRaises(SVC_ERR) as ctx:
            self.call("download_activity", {"activity_id": 1})
        self.assertEqual(ctx.exception.translation_key, "path_not_allowed")
        self.assertEqual(ctx.exception.translation_placeholders["folder"], os.path.join(self.media, DOMAIN))
        self.assertEqual([c for c in self.api.calls if c[0] == "download"], [])

    def test_traversal_is_resolved_before_the_check(self):
        sneaky = os.path.join(self.media, "..", "..", "etc", "x.zip")
        with self.assertRaises(SVC_ERR) as ctx:
            self.call("download_activity", {"activity_id": 1, "path": sneaky})
        self.assertEqual(ctx.exception.translation_key, "path_not_allowed")
        # und ein "..", das im erlaubten Ordner bleibt, geht
        fine = os.path.join(self.media, "a", "..", "b.zip")
        self.assertEqual(self.call("download_activity", {"activity_id": 1, "path": fine})["path"],
                         os.path.join(self.media, "b.zip"))

    def test_symlink_out_of_allowed_folder_is_refused(self):
        os.makedirs(self.media)
        outside = os.path.join(self.root, "outside")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(self.media, "link"))
        with self.assertRaises(SVC_ERR):
            self.call("download_activity", {"activity_id": 1, "path": os.path.join(self.media, "link", "a.zip")})
        self.assertEqual(os.listdir(outside), [])

    def test_prefix_trick(self):
        with self.assertRaises(SVC_ERR):
            self.call("download_activity", {"activity_id": 1, "path": self.media + "_evil/x.zip"})

    def test_folder_path_gets_safe_filename(self):
        os.makedirs(os.path.join(self.media, "sub"))
        for given in (os.path.join(self.media, "sub"), os.path.join(self.media, "sub") + "/"):
            out = self.call("download_activity", {"activity_id": 9, "path": given})
            self.assertEqual(out["path"], os.path.join(self.media, "sub", "activity_9.zip"))

    def test_only_zip_files(self):
        with self.assertRaises(SVC_ERR) as ctx:
            self.call("download_activity", {"activity_id": 1, "path": os.path.join(self.media, "automations.yaml")})
        self.assertEqual(ctx.exception.translation_key, "path_not_zip")
        self.assertEqual([c for c in self.api.calls if c[0] == "download"], [])

    def test_write_error_is_translated_and_leaves_no_part_file(self):
        os.makedirs(self.media)
        blocker = os.path.join(self.media, "file")
        Path(blocker).write_text("x")
        with self.assertRaises(HA_ERR) as ctx:
            self.call("download_activity", {"activity_id": 1, "path": os.path.join(blocker, "a.zip")})
        self.assertEqual(ctx.exception.translation_key, "download_failed")
        self.assertIn("path", ctx.exception.translation_placeholders)

    def test_replace_failure_cleans_up(self):
        from unittest import mock

        os.makedirs(self.media)
        with (
            mock.patch.object(sv.os, "replace", side_effect=OSError(13, "Permission denied")),
            self.assertRaises(HA_ERR) as ctx,
        ):
            self.call("download_activity", {"activity_id": 1, "path": os.path.join(self.media, "a.zip")})
        self.assertEqual(ctx.exception.translation_key, "download_failed")
        self.assertEqual(ctx.exception.translation_placeholders["error"], "Permission denied")
        self.assertEqual(os.listdir(self.media), [])  # keine .part-Datei zurueck


if __name__ == "__main__":
    unittest.main()
