"""intraday.py: reading Garmin's heart rate, Body Battery and SpO2 answers (invented numbers)."""

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402
from intraday_fakes import bb_payload, hr_payload, ms, spo2_payload  # noqa: E402

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

            async def get_body_battery(self, a, b):
                calls.append(("bb", a, b))

            async def get_spo2(self, day):
                calls.append(("spo2", day))

        day = datetime(2026, 10, 24, tzinfo=UTC).date()
        for key in iv.SERIES:
            stubs.run(iv.fetch_series(Api(), key, day))
        self.assertEqual(calls, [("hr", day), ("bb", day, day), ("spo2", day)])


if __name__ == "__main__":
    unittest.main()
