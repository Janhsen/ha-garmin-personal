"""intraday.py: min/max/mean per full UTC hour, closed hours only, time zones (invented numbers)."""

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402
from intraday_fakes import hr_payload, ms  # noqa: E402

stubs.load_full()
iv = sys.modules["gp_full.intraday"]
BERLIN = ZoneInfo("Europe/Berlin")


def utc(*args):
    return datetime(*args, tzinfo=UTC)


class Aggregate(unittest.TestCase):
    def test_min_max_mean_count(self):
        pts = [(ms(2026, 10, 24, 8, 0), 60.0), (ms(2026, 10, 24, 8, 30), 90.0), (ms(2026, 10, 24, 8, 59), 75.0)]
        out = iv.hourly_aggregate(pts)
        self.assertEqual(out, {utc(2026, 10, 24, 8): iv.HourStat(60.0, 90.0, 75.0, 3)})

    def test_hour_boundaries_are_exact(self):
        pts = [(ms(2026, 10, 24, 8, 59) + 59999, 70.0), (ms(2026, 10, 24, 9, 0), 80.0)]
        out = iv.hourly_aggregate(pts)
        self.assertEqual(list(out), [utc(2026, 10, 24, 8), utc(2026, 10, 24, 9)])
        self.assertEqual(out[utc(2026, 10, 24, 9)].count, 1)

    def test_hours_without_points_are_absent_not_filled(self):
        pts = [(ms(2026, 10, 24, 3, 10), 50.0), (ms(2026, 10, 24, 7, 10), 52.0)]
        out = iv.hourly_aggregate(pts)
        self.assertEqual(list(out), [utc(2026, 10, 24, 3), utc(2026, 10, 24, 7)])  # nothing in between

    def test_single_point_hour(self):
        out = iv.hourly_aggregate([(ms(2026, 10, 24, 3, 10), 50.0)])
        self.assertEqual(out[utc(2026, 10, 24, 3)], iv.HourStat(50.0, 50.0, 50.0, 1))

    def test_unsorted_input_and_empty(self):
        pts = [(ms(2026, 10, 24, 9, 5), 1.0), (ms(2026, 10, 24, 8, 5), 2.0)]
        self.assertEqual(list(iv.hourly_aggregate(pts)), sorted(iv.hourly_aggregate(pts)))
        self.assertEqual(iv.hourly_aggregate([]), {})

    def test_mean_is_plain_mean_of_the_points(self):
        pts = [(ms(2026, 10, 24, 8, 0), 60.0), (ms(2026, 10, 24, 8, 1), 60.0), (ms(2026, 10, 24, 8, 50), 90.0)]
        self.assertEqual(iv.hourly_aggregate(pts)[utc(2026, 10, 24, 8)].mean, 70.0)

    def test_hour_start(self):
        self.assertEqual(iv.hour_start(ms(2026, 10, 24, 8, 59)), utc(2026, 10, 24, 8))


class ClosedHours(unittest.TestCase):
    def hours(self):
        return iv.hourly_aggregate([(ms(2026, 10, 24, h, 10), 1.0) for h in (9, 10, 11)])

    def test_running_hour_is_never_included(self):
        closed = iv.closed_hours(self.hours(), utc(2026, 10, 24, 11, 30))
        self.assertEqual(list(closed), [utc(2026, 10, 24, 9), utc(2026, 10, 24, 10)])

    def test_hour_closes_exactly_at_the_full_hour(self):
        self.assertNotIn(utc(2026, 10, 24, 11), iv.closed_hours(self.hours(), utc(2026, 10, 24, 11, 59, 59)))
        self.assertIn(utc(2026, 10, 24, 11), iv.closed_hours(self.hours(), utc(2026, 10, 24, 12, 0)))

    def test_nothing_closed_in_the_past_future_data(self):
        self.assertEqual(iv.closed_hours(self.hours(), utc(2026, 10, 24, 8)), {})

    def test_hours_from_payload(self):
        payload = hr_payload([(ms(2026, 10, 24, 9, 10), 60), (ms(2026, 10, 24, 10, 10), 70)])
        out = iv.hours_from_payload(iv.SERIES["heart_rate"], payload, utc(2026, 10, 24, 10, 30))
        self.assertEqual(list(out), [utc(2026, 10, 24, 9)])
        self.assertIsNone(iv.hours_from_payload(iv.SERIES["heart_rate"], "junk", utc(2026, 10, 24, 10, 30)))


class TimeZones(unittest.TestCase):
    def test_autumn_change_keeps_the_repeated_local_hour_apart(self):
        # Berlin 2026-10-25: 03:00 CEST -> 02:00 CET. Local 02:xx happens twice (00:xx and 01:xx UTC).
        first = datetime(2026, 10, 25, 2, 30, tzinfo=BERLIN, fold=0)
        second = datetime(2026, 10, 25, 2, 30, tzinfo=BERLIN, fold=1)
        pts = [(int(first.timestamp() * 1000), 60.0), (int(second.timestamp() * 1000), 80.0)]
        out = iv.hourly_aggregate(pts)
        self.assertEqual(list(out), [utc(2026, 10, 25, 0), utc(2026, 10, 25, 1)])
        self.assertEqual([s.mean for s in out.values()], [60.0, 80.0])

    def test_spring_change_has_no_row_for_the_missing_local_hour(self):
        # Berlin 2026-03-29: 02:00 CET -> 03:00 CEST; local 02:xx does not exist, UTC 01:xx is the next hour.
        before = datetime(2026, 3, 29, 1, 30, tzinfo=BERLIN)
        after = datetime(2026, 3, 29, 3, 30, tzinfo=BERLIN)
        pts = [(int(before.timestamp() * 1000), 60.0), (int(after.timestamp() * 1000), 70.0)]
        self.assertEqual(list(iv.hourly_aggregate(pts)), [utc(2026, 3, 29, 0), utc(2026, 3, 29, 1)])

    def test_local_midnight_belongs_to_the_utc_hour(self):
        # 00:30 CEST on the 25th is 22:30 UTC on the 24th.
        ts = int(datetime(2026, 10, 24, 0, 30, tzinfo=BERLIN).timestamp() * 1000)
        self.assertEqual(list(iv.hourly_aggregate([(ts, 1.0)])), [utc(2026, 10, 23, 22)])

    def test_closed_hours_across_the_change(self):
        pts = [(ms(2026, 10, 25, h, 20), float(h)) for h in (0, 1, 2)]
        now = datetime(2026, 10, 25, 3, 30, tzinfo=BERLIN)  # 02:30 UTC
        closed = iv.closed_hours(iv.hourly_aggregate(pts), now)
        self.assertEqual(list(closed), [utc(2026, 10, 25, 0), utc(2026, 10, 25, 1)])

    def test_half_hour_zone_boundary_hour_is_dropped_not_written_half(self):
        kolkata = ZoneInfo("Asia/Kolkata")
        midnight = datetime(2026, 10, 24, tzinfo=kolkata)  # 18:30 UTC on the 23rd
        pts = [(int((midnight + timedelta(minutes=m)).timestamp() * 1000), 70.0) for m in (0, 10, 20, 40, 50)]
        hours = iv.hourly_aggregate(pts)
        self.assertEqual(list(hours), [utc(2026, 10, 23, 18), utc(2026, 10, 23, 19)])
        kept = iv.drop_straddling(hours, midnight)
        self.assertEqual(list(kept), [utc(2026, 10, 23, 19)])

    def test_whole_hour_zone_drops_nothing(self):
        hours = iv.hourly_aggregate([(ms(2026, 10, 24, 8, 10), 1.0), (ms(2026, 10, 24, 9, 10), 2.0)])
        self.assertEqual(iv.drop_straddling(hours, utc(2026, 10, 24, 8), utc(2026, 10, 24, 9)), hours)


class Merge(unittest.TestCase):
    def test_timestamp_counts_once_and_result_is_sorted(self):
        a = [(3, 1.0), (1, 2.0)]
        b = [(3, 9.0), (2, 4.0)]
        self.assertEqual(iv.merge_points(a, b), [(1, 2.0), (2, 4.0), (3, 1.0)])

    def test_two_halves_of_an_hour_are_averaged_together(self):
        a = [(ms(2026, 10, 24, 8, 5), 60.0)]
        b = [(ms(2026, 10, 24, 8, 45), 80.0)]
        out = iv.hourly_aggregate(iv.merge_points(a, b))
        self.assertEqual(out[utc(2026, 10, 24, 8)].mean, 70.0)


if __name__ == "__main__":
    unittest.main()
