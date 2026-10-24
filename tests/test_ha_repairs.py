"""Repair issue for the (calculated) key expiry. Invented data only."""

import json
import logging
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402

logging.disable(logging.CRITICAL)
gp = stubs.load_full()
repairs = sys.modules["gp_full.repairs"]
const = sys.modules["gp_full.const"]
ISSUE = ("garmin_personal", "key_expiring_E1")


def entry(expires):
    data = {} if expires is None else {"key_expires_at": expires}
    return stubs.FakeEntry(entry_id="E1", title="Alex", data=data)


def when(**delta):
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


class Issue(unittest.TestCase):
    def setUp(self):
        stubs.ISSUES.clear()
        self.hass = stubs.FakeHass()

    def update(self, e):
        repairs.update_key_expiry_issue(self.hass, e)
        return stubs.ISSUES.get(ISSUE)

    def test_far_away_or_unknown_creates_nothing(self):
        self.assertIsNone(self.update(entry(when(days=30))))
        self.assertIsNone(self.update(entry(None)))
        self.assertIsNone(self.update(entry("not a date")))

    def test_inside_the_warning_window_is_a_warning(self):
        issue = self.update(entry(when(days=3, hours=1)))
        self.assertEqual(issue["translation_key"], "key_expiring")
        self.assertEqual(issue["severity"].name, "WARNING")
        self.assertEqual(issue["translation_placeholders"]["days_left"], "3")
        self.assertEqual(issue["translation_placeholders"]["account"], "Alex")
        self.assertFalse(issue["is_fixable"])

    def test_after_expiry_it_is_an_error_with_its_own_text(self):
        issue = self.update(entry(when(days=-2)))
        self.assertEqual(issue["translation_key"], "key_expired")
        self.assertEqual(issue["severity"].name, "ERROR")
        self.assertEqual(issue["translation_placeholders"]["days_left"], "0")

    def test_warning_turns_into_error_and_back_after_replacing_the_key(self):
        e = entry(when(days=1))
        self.assertEqual(self.update(e)["translation_key"], "key_expiring")
        e.data = {"key_expires_at": when(hours=-1)}
        self.assertEqual(self.update(e)["translation_key"], "key_expired")
        e.data = {"key_expires_at": when(days=90)}
        self.assertIsNone(self.update(e))

    def test_naive_timestamp_is_treated_as_utc(self):
        naive = (datetime.now(UTC) + timedelta(days=2)).replace(tzinfo=None).isoformat()
        self.assertIsNotNone(self.update(entry(naive)))

    def test_remove_deletes_the_issue(self):
        e = entry(when(days=1))
        self.update(e)
        repairs.remove_key_expiry_issue(self.hass, e)
        self.assertNotIn(ISSUE, stubs.ISSUES)

    def test_texts_never_contain_the_key(self):
        e = entry(when(days=1))
        e.data["api_key"] = "SECRET-KEY-123"
        self.assertNotIn("SECRET-KEY-123", json.dumps(self.update(e), default=str))

    def test_check_interval_is_at_most_daily(self):
        self.assertLessEqual(const.KEY_EXPIRY_CHECK_INTERVAL, timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
