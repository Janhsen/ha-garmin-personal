"""Garmin's stress qualifier UNKNOWN must not become Home Assistant's own state "unknown" as a value."""

import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402


class StressQualifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs.load_full()
        sensor = importlib.import_module(f"{stubs.NAME}.sensor")
        cls.desc = next(d for d in sensor.SENSORS if d.key == "stress_qualifier")

    def value(self, qualifier):
        return self.desc.value_fn({"summary": {"stressQualifier": qualifier, "totalSteps": 1, "lastSyncTimestampGMT": "2026-10-24T06:00:00.0"}})

    def test_known_values_are_lower_case_keys(self):
        self.assertEqual(self.value("BALANCED"), "balanced")
        self.assertEqual(self.value("VERY_STRESSFUL"), "very_stressful")

    def test_unknown_in_any_case_is_no_value(self):
        for raw in ("UNKNOWN", "unknown", "Unknown"):
            self.assertIsNone(self.value(raw), raw)

    def test_missing_is_no_value(self):
        self.assertIsNone(self.value(None))


if __name__ == "__main__":
    unittest.main()
