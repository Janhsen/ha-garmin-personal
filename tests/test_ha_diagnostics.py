"""Diagnostics must not leak the key, the account id, the entry title or any values."""

import json
import logging
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402

logging.disable(logging.CRITICAL)
gp = stubs.load_full()
import importlib  # noqa: E402

diag = importlib.import_module("gp_full.diagnostics")

KEY = "SECRET-KEY-ABC123"
PROFILE_ID = "98765432"
TITLE = "Alex Example"


def coord(data, ok=True, error=None):
    return SimpleNamespace(data=data, last_update_success=ok, last_exception=error,
                           update_interval=timedelta(minutes=5))


def make_entry():
    entry = stubs.FakeEntry(
        entry_id="E1", title=TITLE, unique_id=PROFILE_ID, options={"daily_interval_minutes": 10},
        data={"api_key": KEY, "key_validity_days": "90", "account_id_source": "profile_id",
              "key_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat()},
    )
    entry.runtime_data = SimpleNamespace(coordinators={
        "daily": coord({"summary": {"steps": 12345, "latitude": 48.123456, "userProfileId": PROFILE_ID},
                        "hrv": None, "_day": "2026-01-02"}),
        "activities": coord({"activities": [{"activityName": "Morning Run in Exampletown"}], "new_activities": []},
                            ok=False, error=RuntimeError("boom " + KEY)),
    })
    return entry


class Diagnostics(unittest.TestCase):
    def setUp(self):
        stubs.REGISTRY.entries.clear()
        for key, disabled, domain in (("steps", None, "sensor"), ("body_fat", "integration", "sensor"),
                                      ("sleep_score", "user", "sensor"), ("sync_stale", None, "binary_sensor")):
            stubs.REGISTRY.entries[f"E1_{key}"] = stubs.FakeRegistryEntry(
                disabled_by=None if disabled is None else stubs.RegistryEntryDisabler(disabled),
                unique_id=f"E1_{key}", domain=domain, config_entry_id="E1")
        stubs.REGISTRY.entries["E2_other"] = stubs.FakeRegistryEntry(
            unique_id="E2_other", config_entry_id="E2")
        self.result = stubs.run(diag.async_get_config_entry_diagnostics(stubs.FakeHass(), make_entry()))
        self.text = json.dumps(self.result, default=str)

    def test_no_secret_no_account_id_no_title_no_values(self):
        for forbidden in (KEY, PROFILE_ID, TITLE, "12345", "48.123456", "Exampletown", "Morning Run"):
            self.assertNotIn(forbidden, self.text, forbidden)

    def test_entry_section(self):
        entry = self.result["entry"]
        self.assertEqual(entry["data"]["api_key"], "**REDACTED**")
        self.assertEqual(entry["unique_id"], "**REDACTED**")
        self.assertEqual(entry["options"], {"daily_interval_minutes": 10})
        self.assertEqual(entry["version"], "1.1")

    def test_key_section_says_expiry_is_calculated(self):
        key = self.result["key"]
        self.assertIsNotNone(key["expires_at"])
        self.assertIn("calculated", key["expiry_source"])
        self.assertEqual(key["validity_days"], "90")

    def test_groups_show_endpoint_status_only(self):
        daily = self.result["groups"]["daily"]
        self.assertEqual(daily["endpoints_with_data"], ["summary"])
        self.assertEqual(daily["endpoints_empty"], ["hrv"])
        self.assertEqual(daily["data_day"], "2026-01-02")
        self.assertEqual(daily["interval"], "0:05:00")
        broken = self.result["groups"]["activities"]
        self.assertFalse(broken["last_update_success"])
        self.assertEqual(broken["last_exception"], "RuntimeError")  # type only, never the message

    def test_entities_counted_for_this_entry_only(self):
        entities = self.result["entities"]
        self.assertEqual(entities["total"], 4)
        self.assertEqual(entities["enabled"], 2)
        sensor = entities["by_platform"]["sensor"]
        self.assertEqual(sensor["disabled_by_integration"], ["body_fat"])
        self.assertEqual(sensor["disabled_by_user"], ["sleep_score"])
        self.assertEqual(entities["by_platform"]["binary_sensor"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
