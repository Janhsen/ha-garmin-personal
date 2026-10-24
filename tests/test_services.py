"""services.py: _get_entry, _jsonable, _import_statistics, Handler und Fehlerabbildung."""

import logging
import sys
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402

logging.disable(logging.CRITICAL)
gp = stubs.load_full()
sv = sys.modules["gp_full.services"]
api_mod = sys.modules["gp_full.api"]
DOMAIN = "garmin_personal"
SVC_ERR = stubs.ServiceValidationError
HA_ERR = stubs.HomeAssistantError


class FakeRuntime:
    def __init__(self, api):
        self.api = api


class FakeApi:
    def __init__(self):
        self.calls = []
        self.error = None
        self.fetch_result = {"x": 1}
        self.search_result = [{"activityId": 1}]
        self.zip = b"PK\x03\x04data"
        self.summaries = []

    def _maybe_raise(self):
        if self.error:
            raise self.error

    async def fetch(self, endpoint, **kw):
        self.calls.append(("fetch", endpoint, kw))
        self._maybe_raise()
        return self.fetch_result

    async def search_activities(self, **kw):
        self.calls.append(("search", kw))
        self._maybe_raise()
        return self.search_result

    async def download_activity_zip(self, activity_id):
        self.calls.append(("download", activity_id))
        self._maybe_raise()
        return self.zip

    async def get_daily_summaries(self, start, end):
        self.calls.append(("summaries", start, end))
        self._maybe_raise()
        return self.summaries


def make_hass(*entries, config=None):
    hass = stubs.FakeHass(config)
    hass.config_entries.entries = list(entries)
    return hass


def loaded(entry_id="E1", api=None, title="Jan"):
    return stubs.FakeEntry(entry_id=entry_id, title=title, runtime_data=FakeRuntime(api or FakeApi()))


class GetEntry(unittest.TestCase):
    def test_no_entries(self):
        with self.assertRaisesRegex(SVC_ERR, "No Garmin account"):
            sv._get_entry(make_hass(), stubs.FakeCall())

    def test_single_entry_without_id(self):
        e = loaded()
        self.assertIs(sv._get_entry(make_hass(e), stubs.FakeCall()), e)

    def test_several_entries_need_id(self):
        with self.assertRaisesRegex(SVC_ERR, "Several"):
            sv._get_entry(make_hass(loaded("A"), loaded("B")), stubs.FakeCall())

    def test_several_entries_with_id(self):
        a, b = loaded("A"), loaded("B")
        self.assertIs(sv._get_entry(make_hass(a, b), stubs.FakeCall({"config_entry_id": "B"})), b)

    def test_unknown_id(self):
        with self.assertRaisesRegex(SVC_ERR, "Unknown or not loaded"):
            sv._get_entry(make_hass(loaded("A")), stubs.FakeCall({"config_entry_id": "ZZ"}))

    def test_not_loaded_entry_is_ignored(self):
        unloaded = stubs.FakeEntry(entry_id="U")  # kein runtime_data
        none_rt = stubs.FakeEntry(entry_id="N", runtime_data=None)
        ok = loaded("A")
        self.assertIs(sv._get_entry(make_hass(unloaded, none_rt, ok), stubs.FakeCall()), ok)
        with self.assertRaises(SVC_ERR):  # nur nicht geladene -> "kein Konto"
            sv._get_entry(make_hass(unloaded, none_rt), stubs.FakeCall())
        with self.assertRaisesRegex(SVC_ERR, "Unknown or not loaded"):
            sv._get_entry(make_hass(unloaded, ok), stubs.FakeCall({"config_entry_id": "U"}))


class Jsonable(unittest.TestCase):
    def test_nested(self):
        value = {1: (date(2026, 1, 2), [datetime(2026, 1, 2, 3, 4, tzinfo=UTC), {"a": None}]), "b": 2.5}
        self.assertEqual(sv._jsonable(value), {
            "1": ["2026-01-02", ["2026-01-02T03:04:00+00:00", {"a": None}]], "b": 2.5})

    def test_scalars_pass_through(self):
        for v in (None, 1, 1.5, "x", True):
            self.assertIs(sv._jsonable(v), v)


class Registration(unittest.TestCase):
    def test_registers_four_services_once(self):
        hass = make_hass()
        sv.async_register_services(hass)
        self.assertEqual({n for _, n in hass.services.registered},
                         {"fetch", "search_activities", "download_activity", "backfill_statistics"})
        before = dict(hass.services.registered)
        sv.async_register_services(hass)  # idempotent
        self.assertEqual(hass.services.registered, before)

    def test_response_modes(self):
        hass = make_hass()
        sv.async_register_services(hass)
        mode = lambda n: hass.services.registered[(DOMAIN, n)]["supports_response"].name  # noqa: E731
        self.assertEqual((mode("fetch"), mode("search_activities")), ("ONLY", "ONLY"))
        self.assertEqual((mode("download_activity"), mode("backfill_statistics")), ("OPTIONAL", "OPTIONAL"))


class Handlers(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.entry = loaded(api=self.api)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hass = make_hass(self.entry, config=stubs.FakeConfig(self.tmp.name, (self.tmp.name,)))
        sv.async_register_services(self.hass)

    def call(self, name, data=None):
        handler = self.hass.services.registered[(DOMAIN, name)]["handler"]
        return stubs.run(handler(stubs.FakeCall(data)))

    # -- fetch
    def test_fetch_passes_arguments_and_jsonifies(self):
        self.api.fetch_result = {"day": date(2026, 10, 1)}
        out = self.call("fetch", {"endpoint": "steps", "date": date(2026, 10, 1), "limit": 20,
                                  "filters": {"a": 1}})
        self.assertEqual(out, {"endpoint": "steps", "data": {"day": "2026-10-01"}})
        _, endpoint, kw = self.api.calls[0]
        self.assertEqual(endpoint, "steps")
        self.assertEqual(kw, {"day": date(2026, 10, 1), "start": None, "end": None, "activity_id": None,
                              "filters": {"a": 1}, "limit": 20})

    def test_fetch_value_error_becomes_validation_error(self):
        self.api.error = ValueError("bad range")
        with self.assertRaisesRegex(SVC_ERR, "bad range"):
            self.call("fetch", {"endpoint": "steps", "limit": 20})

    def test_fetch_garmin_error_becomes_ha_error(self):
        for exc in (api_mod.GarminAuthError("k"), api_mod.GarminRateLimitError("429"),
                    api_mod.GarminApiError("x", 500)):
            self.api.error = exc
            with self.assertRaises(HA_ERR) as ctx:
                self.call("fetch", {"endpoint": "steps", "limit": 20})
            self.assertNotIsInstance(ctx.exception, SVC_ERR)
            self.assertIn("Garmin request failed", str(ctx.exception))

    # -- search
    def test_search(self):
        out = self.call("search_activities", {"limit": 5, "filters": {"x": 1}})
        self.assertEqual(out, {"count": 1, "activities": [{"activityId": 1}]})
        self.assertEqual(self.api.calls[0], ("search", {"limit": 5, "filters": {"x": 1}}))

    def test_search_errors(self):
        self.api.error = ValueError("filter")
        with self.assertRaises(SVC_ERR):
            self.call("search_activities", {"limit": 5})
        self.api.error = api_mod.GarminApiError("x")
        with self.assertRaises(HA_ERR):
            self.call("search_activities", {"limit": 5})

    # -- download
    def test_download_default_path(self):
        out = self.call("download_activity", {"activity_id": 77})
        expected = Path(self.tmp.name) / DOMAIN / "activity_77.zip"
        self.assertEqual(out, {"path": str(expected), "bytes": len(self.api.zip)})
        self.assertEqual(expected.read_bytes(), self.api.zip)

    def test_download_custom_path_creates_parents(self):
        target = Path(self.tmp.name) / "sub" / "dir" / "a.zip"
        out = self.call("download_activity", {"activity_id": 1, "path": str(target)})
        self.assertEqual(out["path"], str(target))
        self.assertTrue(target.exists())

    def test_download_path_outside_allowlist_rejected_before_request(self):
        with self.assertRaisesRegex(SVC_ERR, "allowlist_external_dirs"):
            self.call("download_activity", {"activity_id": 1, "path": "/etc/passwd"})
        self.assertEqual(self.api.calls, [])

    def test_download_prefix_trick_not_allowed(self):
        evil = self.tmp.name + "_evil/x.zip"  # gleicher Präfix, anderes Verzeichnis
        with self.assertRaises(SVC_ERR):
            self.call("download_activity", {"activity_id": 1, "path": evil})

    def test_download_garmin_error(self):
        self.api.error = api_mod.GarminApiError("x", 404)
        with self.assertRaises(HA_ERR):
            self.call("download_activity", {"activity_id": 1})
        self.assertFalse((Path(self.tmp.name) / DOMAIN).exists())

    @unittest.expectedFailure  # BUG services.py:193-197: OSError beim Schreiben wird nicht abgebildet
    def test_download_unreachable_path_gives_ha_error(self):
        """Schreibfehler (Pfad liegt unter einer Datei) sollten als HomeAssistantError erscheinen."""
        blocker = Path(self.tmp.name) / "file"
        blocker.write_text("x")
        with self.assertRaises(HA_ERR):
            self.call("download_activity", {"activity_id": 1, "path": str(blocker / "a.zip")})

    # -- backfill
    def test_backfill_start_after_end(self):
        with self.assertRaisesRegex(SVC_ERR, "after"):
            self.call("backfill_statistics", {"start_date": date(2026, 2, 1), "end_date": date(2026, 1, 1),
                                              "days": 5})

    def test_backfill_days_window(self):
        self.call("backfill_statistics", {"end_date": date(2026, 10, 10), "days": 10})
        _, start, end = self.api.calls[0]
        self.assertEqual((start, end), (date(2026, 10, 1), date(2026, 10, 10)))  # 10 Tage inklusiv

    def test_backfill_default_end_is_today_local(self):
        orig = sv.dt_util.now
        sv.dt_util.now = lambda: datetime(2026, 5, 5, 23, 0, tzinfo=UTC)
        try:
            self.call("backfill_statistics", {"days": 1})
        finally:
            sv.dt_util.now = orig
        self.assertEqual(self.api.calls[0][1:], (date(2026, 5, 5), date(2026, 5, 5)))

    def test_backfill_error(self):
        self.api.error = api_mod.GarminApiError("x")
        with self.assertRaises(HA_ERR):
            self.call("backfill_statistics", {"days": 3})

    def test_backfill_counts(self):
        self.api.summaries = [
            {"calendarDate": "2026-10-01", "source": "garmin", "totalSteps": 100},
            {"calendarDate": "2026-10-02", "totalSteps": 200},
            {"calendarDate": "2026-10-03", "source": "fitbit", "totalSteps": 300},
        ]
        out = self.call("backfill_statistics", {"days": 3})
        self.assertEqual(out["days_returned"], 3)
        self.assertEqual(out["days_imported"], 2)
        self.assertEqual(out["days_skipped_other_source"], 1)
        self.assertEqual(out["statistics"], 1)  # nur "steps" hat Werte


class ImportStatistics(unittest.TestCase):
    def setUp(self):
        stubs.RECORDED.clear()
        self.hass = make_hass()
        self.entry = stubs.FakeEntry(entry_id="AbC123", title="Jan")
        self.models = sys.modules["homeassistant.components.recorder.models"]

    def run_import(self, summaries):
        n = sv._import_statistics(self.hass, self.entry, summaries)
        return n, {m.kw["statistic_id"].split("_", 2)[-1]: (m, rows) for _, m, rows in stubs.RECORDED}

    def test_only_garmin_or_missing_source(self):
        n, rec = self.run_import([
            {"calendarDate": "2026-10-01", "source": "garmin", "totalSteps": 1},
            {"calendarDate": "2026-10-02", "totalSteps": 2},
            {"calendarDate": "2026-10-03", "source": "fitbit", "totalSteps": 3},
            {"calendarDate": "2026-10-04", "source": "other", "totalSteps": 4},
            "not a dict", None,
        ])
        self.assertEqual(n, 1)
        _, rows = rec["steps"]
        self.assertEqual([r.mean for r in rows], [1.0, 2.0])

    def test_negative_skipped_zero_kept(self):
        _, rec = self.run_import([
            {"calendarDate": "2026-10-01", "totalSteps": -1},
            {"calendarDate": "2026-10-02", "totalSteps": 0},
            {"calendarDate": "2026-10-03", "totalSteps": 5},
        ])
        self.assertEqual([r.mean for r in rec["steps"][1]], [0.0, 5.0])

    def test_all_negative_means_no_statistic(self):
        n, _ = self.run_import([{"calendarDate": "2026-10-01", "totalSteps": -5, "totalKilocalories": -3}])
        self.assertEqual(n, 0)
        self.assertEqual(stubs.RECORDED, [])

    def test_nested_format(self):
        n, rec = self.run_import([{
            "calendarDate": "2026-10-01",
            "movement": {"steps": {"value": 4000, "distanceInMeters": 3100.5}, "floorsAscended": {"value": 7}},
            "calories": {"burnedActive": 300, "burnedResting": 1700, "burnedTotal": 2000},
            "heartRate": {"restingValue": 50, "minValue": 45, "maxValue": 150},
            "stress": {"avgLevel": 30, "maxLevel": 90},
            "bodyBattery": {"maxValue": 90, "minValue": 10, "chargedValue": 60, "drainedValue": 70},
            "intensityMinutes": {"moderate": 20, "vigorous": 5},
            "respiration": {"avgValue": 14},
        }])
        self.assertEqual(n, len(sv.BACKFILL_FIELDS))
        self.assertEqual(rec["steps"][1][0].mean, 4000.0)
        self.assertEqual(rec["distance"][1][0].mean, 3100.5)
        self.assertEqual(rec["floors_ascended"][1][0].mean, 7.0)

    def test_flat_format(self):
        n, rec = self.run_import([{
            "calendarDate": "2026-10-01", "totalSteps": 123, "totalDistanceMeters": 99.5,
            "restingHeartRate": 49, "activeKilocalories": 400,
        }])
        self.assertEqual(n, 4)
        self.assertEqual(rec["resting_heart_rate"][1][0].mean, 49.0)
        self.assertEqual(rec["active_calories"][1][0].mean, 400.0)

    def test_nested_wins_over_flat(self):
        _, rec = self.run_import([{"calendarDate": "2026-10-01", "totalSteps": 1,
                                   "movement": {"steps": {"value": 9}}}])
        self.assertEqual(rec["steps"][1][0].mean, 9.0)

    def test_missing_or_bad_date_skipped(self):
        n, rec = self.run_import([
            {"totalSteps": 1}, {"calendarDate": "", "totalSteps": 2},
            {"calendarDate": "not-a-date", "totalSteps": 3}, {"calendarDate": "2026-10-05", "totalSteps": 4},
        ])
        self.assertEqual([r.mean for r in rec["steps"][1]], [4.0])

    def test_row_fields(self):
        _, rec = self.run_import([{"calendarDate": "2026-10-05", "totalSteps": 4}])
        row = rec["steps"][1][0]
        self.assertEqual(row.start, datetime(2026, 10, 5, tzinfo=UTC))
        self.assertEqual((row.mean, row.min, row.max), (4.0, 4.0, 4.0))

    def test_statistic_id_lowercased_and_metadata(self):
        _, rec = self.run_import([{"calendarDate": "2026-10-05", "totalSteps": 4, "totalDistanceMeters": 1,
                                   "averageStressLevel": 5}])
        meta = rec["steps"][0].kw
        self.assertEqual(meta["statistic_id"], "garmin_personal:abc123_steps")
        self.assertEqual(meta["source"], DOMAIN)
        self.assertEqual(meta["name"], "Jan steps")
        self.assertIs(meta["has_sum"], False)
        self.assertEqual(meta["unit_of_measurement"], "steps")
        self.assertEqual(rec["distance"][0].kw["unit_of_measurement"], "m")
        self.assertEqual(rec["distance"][0].kw["name"], "Jan distance")
        self.assertIsNone(rec["stress_average"][0].kw["unit_of_measurement"])
        self.assertEqual(rec["stress_average"][0].kw["name"], "Jan stress average")
        self.assertEqual(meta["mean_type"], self.models.StatisticMeanType.ARITHMETIC)
        self.assertNotIn("has_mean", meta)

    def test_old_ha_without_mean_type(self):
        saved = self.models.StatisticMeanType
        del self.models.StatisticMeanType
        try:
            _, rec = self.run_import([{"calendarDate": "2026-10-05", "totalSteps": 4}])
        finally:
            self.models.StatisticMeanType = saved
        meta = rec["steps"][0].kw
        self.assertIs(meta["has_mean"], True)
        self.assertNotIn("mean_type", meta)

    def test_unit_class_only_when_annotated(self):
        _, rec = self.run_import([{"calendarDate": "2026-10-05", "totalSteps": 4}])
        self.assertNotIn("unit_class", rec["steps"][0].kw)
        self.models.StatisticMetaData.__annotations__["unit_class"] = str
        try:
            stubs.RECORDED.clear()
            _, rec = self.run_import([{"calendarDate": "2026-10-05", "totalSteps": 4}])
        finally:
            del self.models.StatisticMetaData.__annotations__["unit_class"]
        self.assertIn("unit_class", rec["steps"][0].kw)
        self.assertIsNone(rec["steps"][0].kw["unit_class"])

    def test_empty_input(self):
        self.assertEqual(sv._import_statistics(self.hass, self.entry, []), 0)

    def test_every_field_has_unique_id_suffix_and_paths(self):
        for name, (unit, paths) in sv.BACKFILL_FIELDS.items():
            self.assertTrue(paths, name)
            self.assertRegex(name, r"^[a-z_]+$")


if __name__ == "__main__":
    unittest.main()
