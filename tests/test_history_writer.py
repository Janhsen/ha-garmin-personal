"""history.write_history_states / check_target against fakes of the recorder, registry and state classes."""

import logging
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402
from intraday_fakes import ms  # noqa: E402

logging.disable(logging.CRITICAL)
stubs.load_full()
hs = sys.modules["gp_full.history"]
ha_core = sys.modules["homeassistant.core"]
ha_const = sys.modules["homeassistant.const"]
ha_dt = sys.modules["homeassistant.util.dt"]
ha_rec = sys.modules["homeassistant.components.recorder"]
ha_er = sys.modules["homeassistant.helpers.entity_registry"]
UID = "E1_heart_rate_history"


class FakeState:
    def __init__(self, entity_id, state, attributes=None, *, last_changed, last_reported, last_updated):
        self.entity_id, self.state, self.attributes = entity_id, state, attributes
        self.last_changed, self.last_reported, self.last_updated = last_changed, last_reported, last_updated


class FakeEvent:
    def __init__(self, event_type, data, time_fired_timestamp=None):
        self.event_type, self.data, self.time_fired_timestamp = event_type, data, time_fired_timestamp


class FakeRecorder:
    def __init__(self):
        self.queue = []
        self.entity_filter = None
        self.backlog = 0
        self.fail_after = None

    def queue_task(self, task):
        if self.fail_after is not None and len(self.queue) >= self.fail_after:
            raise RuntimeError("queue closed")
        self.queue.append(task)


class FakeRegistry:
    def __init__(self):
        self.ids = {}
        self.entries = {}

    def async_get_entity_id(self, domain, platform, unique_id):
        return self.ids.get((domain, platform, unique_id))

    def async_get(self, entity_id):
        return self.entries.get(entity_id)


class Base(unittest.TestCase):
    def setUp(self):
        self.rec, self.reg = FakeRecorder(), FakeRegistry()
        self.reg.ids[("sensor", "garmin_personal", UID)] = "sensor.alex_heart_rate_history"
        self.reg.entries["sensor.alex_heart_rate_history"] = type("E", (), {"disabled_by": None})()
        for obj, name, value in (
            (ha_core, "State", FakeState), (ha_core, "Event", FakeEvent),
            (ha_const, "EVENT_STATE_CHANGED", "state_changed"),
            (ha_dt, "utc_from_timestamp", lambda ts: datetime.fromtimestamp(ts, tz=UTC)),
            (ha_rec, "get_instance", lambda hass: self.rec),
            (ha_er, "async_get", lambda hass: self.reg),
        ):
            had, old = hasattr(obj, name), getattr(obj, name, None)
            setattr(obj, name, value)
            self.addCleanup(setattr, obj, name, old) if had else self.addCleanup(delattr, obj, name)
        self.entry = stubs.FakeEntry(entry_id="E1", title="Alex")

    def write(self, points, series="heart_rate"):
        return stubs.run(hs.write_history_states(object(), self.entry, series, points))

    def check(self):
        return stubs.run(hs.check_target(object(), self.entry, "heart_rate"))


T = [ms(2026, 10, 24, 8, m) for m in (0, 2, 4)]


class Target(Base):
    def test_ok(self):
        self.assertEqual(self.check(), "sensor.alex_heart_rate_history")

    def test_missing_disabled_not_recorded(self):
        self.reg.entries["sensor.alex_heart_rate_history"].disabled_by = "user"
        with self.assertRaises(hs.HistoryTargetError) as ctx:
            self.check()
        self.assertEqual((ctx.exception.key, ctx.exception.entity_id), ("history_sensor_disabled", "sensor.alex_heart_rate_history"))
        self.reg.entries["sensor.alex_heart_rate_history"].disabled_by = None
        self.rec.entity_filter = lambda entity_id: False
        with self.assertRaises(hs.HistoryTargetError) as ctx:
            self.check()
        self.assertEqual(ctx.exception.key, "history_not_recorded")
        self.reg.ids.clear()
        with self.assertRaises(hs.HistoryTargetError) as ctx:
            self.check()
        self.assertEqual(ctx.exception.key, "history_sensor_missing")

    def test_filter_that_allows_passes(self):
        self.rec.entity_filter = lambda entity_id: entity_id.startswith("sensor.alex")
        self.assertTrue(self.check())

    def test_unreachable_registry_is_unsupported(self):
        ha_er.async_get = lambda hass: (_ for _ in ()).throw(RuntimeError("no registry"))
        with self.assertRaises(hs.HistoryWriteUnsupported):
            self.check()

    def test_target_problem_writes_nothing(self):
        self.rec.entity_filter = lambda entity_id: False
        with self.assertRaises(hs.HistoryTargetError):
            self.write([(T[0], 60.0)])
        self.assertEqual(self.rec.queue, [])


class Writing(Base):
    def test_events_ascending_with_real_times_and_chained_old_state(self):
        done, err = self.write([(T[2], 64.0), (T[0], 60.0), (T[1], 61.5)])
        self.assertEqual((done, err), (3, None))
        events = self.rec.queue
        self.assertEqual([e.time_fired_timestamp for e in events], [t / 1000 for t in T])
        states = [e.data["new_state"] for e in events]
        self.assertEqual([s.state for s in states], ["60", "61.5", "64"])
        self.assertEqual([s.last_updated for s in states], [datetime.fromtimestamp(t / 1000, tz=UTC) for t in T])
        for s in states:
            self.assertEqual((s.last_changed, s.last_reported), (s.last_updated, s.last_updated))
            self.assertEqual(s.attributes, {"unit_of_measurement": "bpm"})
        self.assertIs(events[1].data["old_state"], states[0])
        self.assertIs(events[2].data["old_state"], states[1])
        self.assertIs(events[0].data["old_state"], states[0])  # first point: never None
        self.assertTrue(all(e.data["old_state"] is not None and e.event_type == "state_changed" for e in events))
        self.assertEqual({e.data["entity_id"] for e in events}, {"sensor.alex_heart_rate_history"})

    def test_cancellation_reports_how_many_points_were_handed_over(self):
        import asyncio

        orig = hs.YIELD_EVERY
        hs.YIELD_EVERY = 2
        self.addCleanup(setattr, hs, "YIELD_EVERY", orig)
        points = [(ms(2026, 10, 24, 8, m), 60.0 + m) for m in range(10)]

        async def scenario():
            task = asyncio.ensure_future(hs.write_history_states(object(), self.entry, "heart_rate", points))
            await asyncio.sleep(0)  # runs up to the first pause (after 2 points)
            task.cancel()
            return await asyncio.gather(task, return_exceptions=True)

        (result,) = stubs.run(scenario())
        self.assertIsInstance(result, hs.HistoryWriteCancelled)
        self.assertEqual(result.done, len(self.rec.queue))  # exactly what reached the recorder
        self.assertEqual(result.done, 2)

    def test_percent_series_unit(self):
        self.reg.ids[("sensor", "garmin_personal", "E1_spo2_history")] = "sensor.alex_spo2_history"
        self.reg.entries["sensor.alex_spo2_history"] = type("E", (), {"disabled_by": None})()
        self.write([(T[0], 95.0)], series="spo2")
        self.assertEqual(self.rec.queue[0].data["new_state"].attributes["unit_of_measurement"], "%")

    def test_nothing_goes_through_the_event_bus(self):
        class Hass:
            class bus:  # noqa: N801
                @staticmethod
                def async_fire(*a, **k):
                    raise AssertionError("the bus must not be used")

            class states:  # noqa: N801
                @staticmethod
                def async_set(*a, **k):
                    raise AssertionError("the state machine must not be used")

        self.assertEqual(stubs.run(hs.write_history_states(Hass(), self.entry, "heart_rate", [(T[0], 60.0)])), (1, None))

    def test_failure_returns_the_prefix_that_went_through(self):
        self.rec.fail_after = 2
        self.assertEqual(self.write([(t, 60.0) for t in T]), (2, "queue closed"))
        self.assertEqual(len(self.rec.queue), 2)

    def test_full_recorder_queue_stops_with_a_partial_result(self):
        self.rec.backlog = hs.MAX_RECORDER_BACKLOG + 1
        points = [(T[0] + i * 1000, 60.0) for i in range(hs.YIELD_EVERY + 5)]
        done, err = self.write(points)
        self.assertEqual((done, err), (hs.YIELD_EVERY, "recorder queue is full"))

    def test_empty_input(self):
        self.assertEqual(self.write([]), (0, None))
        self.assertEqual(self.rec.queue, [])

    def test_bad_state_class_is_a_partial_result_not_an_exception(self):
        ha_core.State = lambda *a, **k: (_ for _ in ()).throw(TypeError("signature changed"))
        self.assertEqual(self.write([(T[0], 60.0)]), (0, "signature changed"))
        self.assertEqual(self.rec.queue, [])


if __name__ == "__main__":
    unittest.main()
