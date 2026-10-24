import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _load import load  # noqa: E402

v = load().values


class Basics(unittest.TestCase):
    def test_dig(self):
        d = {"a": {"b": [1, {"c": 5}]}}
        self.assertEqual(v.dig(d, "a", "b", 1, "c"), 5)
        self.assertIsNone(v.dig(d, "a", "x", "c"))
        self.assertIsNone(v.dig(d, "a", "b", 9))
        self.assertIsNone(v.dig("text", 0))

    def test_to_number(self):
        self.assertEqual(v.to_number(3), 3)
        self.assertIsNone(v.to_number(True))
        self.assertIsNone(v.to_number("3"))

    def test_timestamps(self):
        self.assertEqual(v.parse_timestamp(1_700_000_000_000), datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC))
        self.assertEqual(v.parse_timestamp("2026-05-01T06:30:00.0"), datetime(2026, 5, 1, 6, 30, tzinfo=UTC))
        self.assertEqual(v.parse_timestamp("2026-05-01T08:30:00+02:00"), datetime(2026, 5, 1, 6, 30, tzinfo=UTC))
        self.assertIsNone(v.parse_timestamp("garbage"))
        self.assertIsNone(v.parse_timestamp(None))
        self.assertIsNone(v.parse_timestamp(10**30))

    def test_number_at_scale(self):
        f = v.number_at("w", scale=1000, digits=2)
        self.assertEqual(f({"w": 81234}), 81.23)
        self.assertIsNone(f({}))

    def test_text_limits(self):
        self.assertEqual(len(v.text_at("t")({"t": "x" * 400})), 255)
        self.assertIsNone(v.text_at("t")({"t": {"a": 1}}))


class Domain(unittest.TestCase):
    def test_latest_weight_picks_newest_day(self):
        data = {"weight": {"dailyWeightSummaries": [
            {"summaryDate": "2026-05-01", "latestWeight": {"weight": 80000}},
            {"summaryDate": "2026-05-03", "latestWeight": {"weight": 79000}},
            {"summaryDate": "2026-05-02", "latestWeight": None},
        ]}}
        self.assertEqual(v.weight_at("weight", scale=1000)(data), 79.0)
        self.assertIsNone(v.weight_at("weight")({"weight": None}))

    def test_hr_zones_default_sport(self):
        data = {"hr_zones": [{"sport": "RUNNING", "maxHeartRateUsed": 190}, {"sport": "DEFAULT", "maxHeartRateUsed": 185}]}
        self.assertEqual(v.hr_zone_at("maxHeartRateUsed")(data), 185)
        self.assertEqual(v.hr_zone_at("maxHeartRateUsed")({"hr_zones": [{"maxHeartRateUsed": 180}]}), 180)
        self.assertIsNone(v.hr_zone_at("x")({}))

    def test_item_helpers(self):
        data = {"hrv_summaries": [{"lastNightAvg": 40}, {"lastNightAvg": 55}], "activities": [{"activityName": "Run", "distance": 5000.0, "startTimeGMT": "2026-05-01 06:00:00"}]}
        self.assertEqual(v.item_number("hrv_summaries", "lastNightAvg")(data), 55)
        self.assertEqual(v.activity_text("activityName")(data), "Run")
        self.assertEqual(v.activity_number("distance")(data), 5000.0)
        self.assertEqual(v.activity_timestamp("startTimeGMT")(data), datetime(2026, 5, 1, 6, tzinfo=UTC))
        self.assertIsNone(v.activity_number("distance")({}))

    def test_series_pairs(self):
        rows = [[1000, 60], [2000, None], [3000, 70], "bad", [4000]]
        self.assertEqual(v.series_pairs(rows), [[1000, 60], [3000, 70]])
        self.assertEqual(v.series_pairs(None), [])


if __name__ == "__main__":
    unittest.main()
