"""event.py (keine doppelten Events) und binary_sensor.py (sync_stale an/aus/unbekannt)."""

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
ev = sys.modules["gp_full.event"]
bs = sys.modules["gp_full.binary_sensor"]
const = sys.modules["gp_full.const"]


def activity(i, **extra):
    return {"activityId": i, "activityName": f"A{i}", "activityType": {"typeKey": "running"},
            "startTimeGMT": "2026-10-01 06:00:00", "distance": 1000.0, "duration": 300.0, "calories": 90,
            **extra}


class EventTests(unittest.TestCase):
    def setUp(self):
        self.coord = SimpleNamespace(data=None)
        self.entity = ev.GarminActivityEvent(self.coord, stubs.FakeEntry(entry_id="E1"))

    def push(self, new, **data):
        self.coord.data = {"new_activities": new, **data}
        self.entity._handle_coordinator_update()

    def fired_ids(self):
        return [d["activity_id"] for _, d in self.entity.triggered]

    def test_attributes(self):
        self.assertEqual(self.entity._attr_unique_id, "E1_activity")
        self.assertEqual(self.entity._attr_event_types, ["activity_finished"])

    def test_no_data_or_empty_fires_nothing(self):
        self.entity._handle_coordinator_update()
        self.push([])
        self.coord.data = {}
        self.entity._handle_coordinator_update()
        self.assertEqual(self.entity.triggered, [])
        self.assertEqual(self.entity.state_writes, 3)  # State wird trotzdem geschrieben

    def test_fires_once_per_activity(self):
        self.push([activity(5)])
        self.push([activity(5)])  # Listener nach fehlgeschlagenem Update: Daten bleiben gleich
        self.push([activity(5)])
        self.assertEqual(self.fired_ids(), [5])

    def test_event_payload(self):
        self.push([activity(5)])
        etype, data = self.entity.triggered[0]
        self.assertEqual(etype, "activity_finished")
        self.assertEqual(data, {"activity_id": 5, "name": "A5", "type": "running",
                                "start_time_gmt": "2026-10-01 06:00:00", "distance": 1000.0,
                                "duration": 300.0, "calories": 90})

    def test_payload_with_sparse_activity(self):
        self.push([{"activityId": 1}])
        self.assertEqual(self.entity.triggered[0][1],
                         {"activity_id": 1, "name": None, "type": None, "start_time_gmt": None,
                          "distance": None, "duration": None, "calories": None})

    def test_only_newer_ids_fire(self):
        self.push([activity(5)])
        self.push([activity(5), activity(7)])
        self.push([activity(3)])
        self.push([activity(6)])  # älter als 7
        self.assertEqual(self.fired_ids(), [5, 7])

    def test_several_new_in_one_update_fire_in_order(self):
        self.push([activity(5), activity(6), activity(8)])
        self.assertEqual(self.fired_ids(), [5, 6, 8])
        self.push([activity(5), activity(6), activity(8)])
        self.assertEqual(self.fired_ids(), [5, 6, 8])

    def test_non_int_ids_ignored(self):
        self.push([{"activityId": "9"}, {"activityId": None}, {"name": "x"}])
        self.assertEqual(self.entity.triggered, [])

    def test_each_update_writes_state(self):
        self.push([activity(5)])
        self.push([activity(5)])
        self.assertEqual(self.entity.state_writes, 2)


class SyncStaleTests(unittest.TestCase):
    def sensor(self, data, options=None):
        coord = SimpleNamespace(data=data)
        return bs.GarminSyncStaleSensor(coord, stubs.FakeEntry(entry_id="E1", options=options))

    @staticmethod
    def summary(ago_hours):
        ts = datetime.now(UTC) - timedelta(hours=ago_hours)
        return {"summary": {"lastSyncTimestampGMT": ts.strftime("%Y-%m-%dT%H:%M:%S.0")}}

    def test_attributes(self):
        s = self.sensor(None)
        self.assertEqual(s._attr_unique_id, "E1_sync_stale")
        self.assertEqual(s._attr_translation_key, "sync_stale")

    def test_unknown_without_data(self):
        self.assertIsNone(self.sensor(None).is_on)
        self.assertIsNone(self.sensor({}).is_on)

    def test_unknown_without_sync_timestamp(self):
        self.assertIsNone(self.sensor({"summary": {}}).is_on)
        self.assertIsNone(self.sensor({"summary": None}).is_on)
        self.assertIsNone(self.sensor({"other": 1}).is_on)

    def test_unknown_with_unparseable_timestamp(self):
        self.assertIsNone(self.sensor({"summary": {"lastSyncTimestampGMT": "gestern"}}).is_on)

    def test_off_when_recent(self):
        self.assertIs(self.sensor(self.summary(1)).is_on, False)

    def test_on_when_older_than_default(self):
        self.assertEqual(const.DEFAULT_SYNC_STALE_HOURS, 18)
        self.assertIs(self.sensor(self.summary(19)).is_on, True)
        self.assertIs(self.sensor(self.summary(17)).is_on, False)

    def test_option_overrides_threshold(self):
        opts = {const.OPT_SYNC_STALE_HOURS: 2}
        self.assertIs(self.sensor(self.summary(3), opts).is_on, True)
        self.assertIs(self.sensor(self.summary(1), opts).is_on, False)
        opts = {const.OPT_SYNC_STALE_HOURS: 48}
        self.assertIs(self.sensor(self.summary(13), opts).is_on, False)

    def test_exact_threshold_is_not_stale(self):
        fixed = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
        orig = bs.dt_util.utcnow
        bs.dt_util.utcnow = lambda: fixed
        try:
            at = {"summary": {"lastSyncTimestampGMT": (fixed - timedelta(hours=18)).isoformat()}}
            over = {"summary": {"lastSyncTimestampGMT": (fixed - timedelta(hours=18, seconds=1)).isoformat()}}
            self.assertIs(self.sensor(at).is_on, False)
            self.assertIs(self.sensor(over).is_on, True)
        finally:
            bs.dt_util.utcnow = orig

    def test_epoch_milliseconds_timestamp(self):
        ms = int((datetime.now(UTC) - timedelta(hours=20)).timestamp() * 1000)
        self.assertIs(self.sensor({"summary": {"lastSyncTimestampGMT": ms}}).is_on, True)


if __name__ == "__main__":
    unittest.main()
