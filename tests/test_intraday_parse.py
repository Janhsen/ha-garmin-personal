"""intraday.py: reading Garmin's heart rate, Body Battery and SpO2 answers (invented numbers)."""

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402
from intraday_fakes import (  # noqa: E402
    bb_payload,
    hr_payload,
    hrv_payload,
    ms,
    spo2_payload,
    spo2_payload3,
)

stubs.load_full()
iv = sys.modules["gp_full.intraday"]

T0 = ms(2026, 10, 24, 8, 0)
T1 = ms(2026, 10, 24, 8, 2)


class HeartRate(unittest.TestCase):
    def test_pairs_with_descriptors(self):
        self.assertEqual(iv.heart_rate_points(hr_payload([(T0, 61), (T1, 64)])), [(T0, 61.0), (T1, 64.0)])

    def test_without_descriptors_uses_the_first_two_columns(self):
        self.assertEqual(iv.heart_rate_points(hr_payload([(T0, 61)], descriptors=False)), [(T0, 61.0)])

    def test_descriptor_columns_are_followed(self):
        payload = {"heartRateValues": [[70, T0]],
                   "heartRateValueDescriptors": [{"key": "heartrate", "index": 0}, {"key": "timestamp", "index": 1}]}
        self.assertEqual(iv.heart_rate_points(payload), [(T0, 70.0)])

    def test_placeholders_and_junk_are_dropped(self):
        rows = [(T0, 0), (T1, -1), (T1 + 1, None), (T1 + 2, "70"), (T1 + 3, True),
                (T1 + 4, float("nan")), (None, 70), (5, 70), (10**15, 70), (T1 + 5, 72)]
        rows.append("not a row")
        rows.append([T0])
        self.assertEqual(iv.heart_rate_points({"heartRateValues": [list(r) if isinstance(r, tuple) else r for r in rows]}),
                         [(T1 + 5, 72.0)])

    def test_missing_or_empty_is_no_data(self):
        self.assertEqual(iv.heart_rate_points(None), [])
        self.assertEqual(iv.heart_rate_points({"heartRateValues": None}), [])
        self.assertEqual(iv.heart_rate_points({"heartRateValues": []}), [])

    def test_unknown_shapes_are_none(self):
        for payload in ("x", 5, [], [1], {"other": 1}, {"heartRateValues": "x"}, {"heartRateValues": {"a": 1}}):
            self.assertIsNone(iv.heart_rate_points(payload), payload)


class BodyBattery(unittest.TestCase):
    def test_level_column_is_looked_up(self):
        self.assertEqual(iv.body_battery_points(bb_payload([(T0, 80), (T1, 79)])), [(T0, 80.0), (T1, 79.0)])

    def test_single_report_and_zero_level(self):
        report = bb_payload([(T0, 0)])[0]
        self.assertEqual(iv.body_battery_points(report), [(T0, 0.0)])  # 0 is a real level

    def test_negative_and_missing_levels_are_dropped(self):
        self.assertEqual(iv.body_battery_points(bb_payload([(T0, -1), (T1, None), (T1 + 1, 55)])), [(T1 + 1, 55.0)])

    def test_no_level_descriptor_means_unknown_format(self):
        report = bb_payload([(T0, 80)])[0]
        report["bodyBatteryValueDescriptorDTOList"] = [
            {"bodyBatteryValueDescriptorIndex": 0, "bodyBatteryValueDescriptorKey": "timestamp"}]
        self.assertIsNone(iv.body_battery_points([report]))
        report["bodyBatteryValueDescriptorDTOList"] = None
        self.assertIsNone(iv.body_battery_points([report]))

    def test_empty_and_unknown(self):
        self.assertEqual(iv.body_battery_points(None), [])
        self.assertEqual(iv.body_battery_points([]), [])
        self.assertEqual(iv.body_battery_points([None]), [])
        self.assertEqual(iv.body_battery_points([{"bodyBatteryValuesArray": None}]), [])
        for payload in ("x", 3, [{"a": 1}], [1], {"a": 1}):
            self.assertIsNone(iv.body_battery_points(payload), payload)

    def test_two_reports_are_combined(self):
        a, b = bb_payload([(T0, 80)])[0], bb_payload([(T1, 70)])[0]
        self.assertEqual(iv.body_battery_points([a, b]), [(T0, 80.0), (T1, 70.0)])


class SpO2(unittest.TestCase):
    def test_hourly_averages(self):
        self.assertEqual(iv.spo2_points(spo2_payload([(T0, 96), (T0 + 3600000, 94)])),
                         [(T0, 96.0), (T0 + 3600000, 94.0)])

    def test_placeholders_dropped(self):
        self.assertEqual(iv.spo2_points(spo2_payload([(T0, 0), (T1, -1), (T1 + 1, 93)])), [(T1 + 1, 93.0)])

    def test_empty_and_unknown(self):
        self.assertEqual(iv.spo2_points(None), [])
        self.assertEqual(iv.spo2_points({"spO2HourlyAverages": None}), [])
        for payload in ("x", [], {"averageSpO2": 95}, {"spO2HourlyAverages": 5}):
            self.assertIsNone(iv.spo2_points(payload), payload)


class Registry(unittest.TestCase):
    def test_series_names_and_units(self):
        self.assertEqual({k: (s.stat_name, s.unit) for k, s in iv.SERIES.items()},
                         {"heart_rate": ("heart_rate_hourly", "bpm"),
                          "body_battery": ("body_battery_hourly", "%"),
                          "spo2": ("spo2_hourly", "%")})

    def test_fetch_series_asks_once_per_series(self):
        calls = []

        class Api:
            async def get_heart_rate(self, day):
                calls.append(("hr", day))

            async def get_body_battery(self, a, b, chunks=None):
                calls.append(("bb", a, b))

            async def get_spo2(self, day):
                calls.append(("spo2", day))

        day = datetime(2026, 10, 24, tzinfo=UTC).date()
        for key in iv.SERIES:
            stubs.run(iv.fetch_series(Api(), key, day))
        self.assertEqual(calls, [("hr", day), ("bb", day, day), ("spo2", day)])


class Spo2Columns(unittest.TestCase):
    def test_level_column_from_the_descriptor_list(self):
        payload = spo2_payload3([(T0, 96, 340), (T0 + 3600000, 94, 12)])
        self.assertEqual(iv.spo2_points(payload), [(T0, 96.0), (T0 + 3600000, 94.0)])

    def test_moved_columns_are_followed_and_the_environment_is_never_read(self):
        payload = spo2_payload3([(340, 96, T0)], order=("monitoringEnvironmentLevel", "spo2Level", "timestamp"))
        self.assertEqual(iv.spo2_points(payload), [(T0, 96.0)])
        only_env = spo2_payload3([(T0, 340)], order=("timestamp", "monitoringEnvironmentLevel"))
        self.assertEqual(iv.spo2_points(only_env), [(T0, 340.0)])  # no spo2Level named: classic column 1 (as before)

    def test_null_levels_are_dropped(self):
        payload = spo2_payload3([(T0, None, 340), (T0 + 3600000, 0, 3), (T0 + 7200000, 95, None)])
        self.assertEqual(iv.spo2_points(payload), [(T0 + 7200000, 95.0)])

    def test_without_descriptor_list_the_classic_layout_applies(self):
        self.assertEqual(iv.spo2_points({"spO2HourlyAverages": [[T0, 97, 5]]}), [(T0, 97.0)])


class Hrv(unittest.TestCase):
    def test_readings_use_the_gmt_time_as_utc(self):
        payload = hrv_payload([("2026-10-24T01:05:00.0", 61), ("2026-10-24T01:10:00.0", 64.5)])
        t = ms(2026, 10, 24, 1, 5)
        self.assertEqual(iv.hrv_points(payload), [(t, 61.0), (t + 300000, 64.5)])

    def test_other_iso_spellings(self):
        t = ms(2026, 10, 24, 1, 5)
        for text in ("2026-10-24T01:05:00", "2026-10-24T01:05:00Z", "2026-10-24T03:05:00+02:00", "2026-10-24 01:05:00.000"):
            self.assertEqual(iv.hrv_points(hrv_payload([(text, 50)])), [(t, 50.0)], text)

    def test_night_across_midnight_keeps_exact_times(self):
        points = iv.hrv_points(hrv_payload([("2026-10-23T22:55:00.0", 40), ("2026-10-24T00:00:00.0", 52)]))
        self.assertEqual([p[0] for p in points], [ms(2026, 10, 23, 22, 55), ms(2026, 10, 24, 0, 0)])

    def test_placeholders_and_broken_rows_are_dropped_low_values_stay(self):
        rows = [("2026-10-24T01:00:00.0", 0), ("2026-10-24T01:05:00.0", -1), ("2026-10-24T01:10:00.0", None),
                ("2026-10-24T01:15:00.0", 22), ("bad", 50), (None, 50)]
        self.assertEqual(iv.hrv_points(hrv_payload(rows)), [(ms(2026, 10, 24, 1, 15), 22.0)])
        payload = hrv_payload([])
        payload["hrvReadings"] += ["x", {"hrvValue": 50}, {"readingTimeGMT": "2026-10-24T01:00:00.0"}]
        self.assertEqual(iv.hrv_points(payload), [])

    def test_empty_and_unknown(self):
        self.assertEqual(iv.hrv_points(None), [])
        self.assertEqual(iv.hrv_points({"hrvReadings": None}), [])
        self.assertEqual(iv.hrv_points({"hrvSummary": {"weeklyAvg": 50}}), [])
        for payload in ({"other": 1}, [], "x", {"hrvReadings": {"a": 1}}):
            self.assertIsNone(iv.hrv_points(payload), payload)

    def test_hrv_is_a_history_series_but_has_no_hourly_statistic(self):
        self.assertIn("hrv", iv.HISTORY_SERIES)
        self.assertNotIn("hrv", iv.SERIES)


if __name__ == "__main__":
    unittest.main()
