"""Koordinatoren: Tageswechsel, Neustart, Fehlerisolation, Halten bei Ausfall, Aktivitäts-Events."""

import logging
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402

logging.disable(logging.CRITICAL)
gp = stubs.load_full()
co = sys.modules["gp_full.coordinator"]
api_mod = sys.modules["gp_full.api"]
ev = sys.modules["gp_full.event"]
bs = sys.modules["gp_full.binary_sensor"]
dt_util = sys.modules["homeassistant.util.dt"]

CLOCK = {"now": datetime(2026, 5, 1, 12, 0, tzinfo=UTC)}
dt_util.now = lambda: CLOCK["now"]
dt_util.utcnow = lambda: CLOCK["now"]


def at(day, hour=12, minute=0):
    CLOCK["now"] = datetime(2026, 5, day, hour, minute, tzinfo=UTC)


def ok(value):
    async def call():
        return value

    return call


def boom(exc):
    async def call():
        raise exc

    return call


class Calls:
    def __init__(self, *cycles):
        self.cycles = list(cycles)

    def __call__(self, api, today):
        return self.cycles.pop(0) if len(self.cycles) > 1 else self.cycles[0]


def make(cls, calls, sticky=(), group="g", entry_id="E1"):
    entry = stubs.FakeEntry(entry_id=entry_id, title="Jan")
    return cls(stubs.FakeHass(), entry, object(), group, timedelta(minutes=5), calls, sticky=sticky)


def refresh(c):
    stubs.run(c.async_refresh())
    return c.data


def summary(sync, **extra):
    return {"lastSyncTimestampGMT": sync, "totalSteps": 1, **extra}


class DayChange(unittest.TestCase):
    def setUp(self):
        at(1)

    def test_values_of_yesterday_are_not_passed_on_as_today(self):
        # Day 2, 00:05: the summary is a placeholder without sync time; spo2 and hydration
        # must be asked again instead of carrying yesterday's answers.
        c = make(co.GarminDailyCoordinator, Calls(
            {"summary": ok(summary("t1")), "spo2": ok({"v": 1}), "hydration": ok([{"v": 2}])},
            {"summary": ok({"calendarDate": "2026-05-02"}), "spo2": ok(None), "hydration": ok([])},
        ))
        refresh(c)
        at(2, 0, 5)
        data = refresh(c)
        self.assertIsNone(data["spo2"])
        self.assertEqual(data["hydration"], [])
        self.assertEqual(data["_day"], "2026-05-02")

    def test_new_day_forces_a_full_refresh_even_without_a_sync_change(self):
        spo2 = []

        async def fetch_spo2():
            spo2.append(1)
            return {"v": len(spo2)}

        calls = Calls({"summary": ok(summary("t1")), "spo2": fetch_spo2})
        c = make(co.GarminDailyCoordinator, calls)
        refresh(c)
        refresh(c)  # same day, same sync: skipped
        self.assertEqual(len(spo2), 1)
        at(2, 0, 5)
        refresh(c)
        self.assertEqual(len(spo2), 2)

    def test_failing_endpoint_keeps_value_the_same_day_but_not_the_next(self):
        c = make(co.GarminDailyCoordinator, Calls(
            {"summary": ok(summary("t1")), "spo2": ok({"v": 1})},
            {"summary": ok(summary("t2")), "spo2": boom(api_mod.GarminApiError("x", 500))},
            {"summary": ok(summary("t3")), "spo2": boom(api_mod.GarminApiError("x", 500))},
        ))
        refresh(c)
        self.assertEqual(refresh(c)["spo2"], {"v": 1})  # sticky for the daily group, same day
        at(2, 0, 5)
        self.assertIsNone(refresh(c)["spo2"])  # next day: nothing of yesterday

    def test_failing_summary_does_not_leave_yesterdays_values_on_a_new_day(self):
        c = make(co.GarminDailyCoordinator, Calls(
            {"summary": ok(summary("t1")), "spo2": ok({"v": 1})},
            {"summary": boom(api_mod.GarminApiError("x", 500)), "spo2": ok({"v": 9})},
        ))
        refresh(c)
        at(2, 0, 5)
        refresh(c)
        # the only executed endpoint failed and yesterday's data must not stand in for today:
        # the group reports the failure instead of showing old values as current
        self.assertFalse(c.last_update_success)


class RestartAndFollowers(unittest.TestCase):
    def setUp(self):
        at(1)

    def wake_count(self, c):
        follower = make(co.GarminCoordinator, Calls({"a": ok(1)}))
        c.followers = [follower]
        return follower

    def test_first_sync_of_the_day_after_a_restart_wakes_the_followers(self):
        c = make(co.GarminDailyCoordinator, Calls(
            {"summary": ok({"calendarDate": "2026-05-01"})},  # restart at night: no sync time yet
            {"summary": ok(summary("t1"))},
        ))
        follower = self.wake_count(c)
        refresh(c)
        stubs.run(c.hass.run_tasks())
        self.assertEqual(follower.refresh_requests, 0)
        refresh(c)
        stubs.run(c.hass.run_tasks())
        self.assertEqual(follower.refresh_requests, 1)

    def test_very_first_cycle_with_a_sync_time_does_not_wake_them(self):
        # (the setup refreshes the followers itself)
        c = make(co.GarminDailyCoordinator, Calls({"summary": ok(summary("t1"))}))
        follower = self.wake_count(c)
        refresh(c)
        stubs.run(c.hass.run_tasks())
        self.assertEqual(follower.refresh_requests, 0)

    def test_last_known_sync_travels_with_the_data(self):
        c = make(co.GarminDailyCoordinator, Calls(
            {"summary": ok(summary("t1"))}, {"summary": ok({"calendarDate": "2026-05-02"})}))
        self.assertEqual(refresh(c)["_last_sync"], "t1")
        at(2, 0, 5)
        self.assertEqual(refresh(c)["_last_sync"], "t1")

    def test_last_sync_is_none_when_never_seen(self):
        c = make(co.GarminDailyCoordinator, Calls({"summary": ok({"calendarDate": "2026-05-01"})}))
        self.assertIsNone(refresh(c)["_last_sync"])


class Isolation(unittest.TestCase):
    def setUp(self):
        at(1)

    def test_malformed_endpoint_only_empties_itself(self):
        for exc in (AttributeError("list has no get"), TypeError("x"), KeyError("k"), ValueError("v")):
            c = make(co.GarminCoordinator, Calls({"a": ok(1), "bad": boom(exc), "c": ok(3)}))
            data = refresh(c)
            self.assertEqual((data["a"], data["bad"], data["c"]), (1, None, 3), exc)

    def test_failing_endpoint_keeps_last_value_in_any_group(self):
        c = make(co.GarminCoordinator, Calls(
            {"a": ok(1), "b": ok([{"x": 1}])},
            {"a": ok(2), "b": boom(api_mod.GarminApiError("x", 500))},
        ))
        refresh(c)
        data = refresh(c)
        self.assertEqual((data["a"], data["b"]), (2, [{"x": 1}]))

    def test_wellness_activities_do_not_cross_midnight(self):
        c = make(co.GarminCoordinator, Calls(
            {"wellness_activities": ok([1]), "a": ok(1)},
            {"wellness_activities": boom(api_mod.GarminApiError("x")), "a": ok(1)},
        ))
        refresh(c)
        at(2, 0, 5)
        self.assertIsNone(refresh(c)["wellness_activities"])


class Sticky(unittest.TestCase):
    def setUp(self):
        at(1)

    def test_nested_empty_answers_count_as_empty(self):
        good = {"dailySleepDTO": {"sleepTimeSeconds": 100}}
        for empty in ({"dailySleepDTO": {"sleepTimeSeconds": None, "x": None}},
                      {"dailySleepDTO": {}}, {"a": {"b": [None, {}]}}):
            c = make(co.GarminCoordinator, Calls({"w": ok(good)}, {"w": ok(empty)}), sticky=("w",))
            refresh(c)
            self.assertEqual(refresh(c)["w"], good, empty)

    def test_nested_value_is_not_empty(self):
        c = make(co.GarminCoordinator, Calls({"w": ok({"a": 1})}, {"w": ok({"a": {"b": 0}})}),
                 sticky=("w",))
        refresh(c)
        self.assertEqual(refresh(c)["w"], {"a": {"b": 0}})

    def test_zero_duration_sleep_is_no_measurement(self):
        good = {"dailySleepDTO": {"sleepTimeSeconds": 100}}
        for zero in ({"dailySleepDTO": {"sleepTimeSeconds": 0, "calendarDate": "2026-05-02"}},
                     {"sleepTimeSeconds": -5, "calendarDate": "2026-05-02"}):
            c = make(co.GarminCoordinator, Calls({"sleep": ok(good)}, {"sleep": ok(zero)}),
                     sticky=("sleep",))
            refresh(c)
            self.assertEqual(refresh(c)["sleep"]["sleepTimeSeconds"], 100, zero)

    def test_positive_sleep_replaces_previous(self):
        c = make(co.GarminCoordinator, Calls({"sleep": ok({"sleepTimeSeconds": 100})},
                                             {"sleep": ok({"sleepTimeSeconds": 200})}),
                 sticky=("sleep",))
        refresh(c)
        self.assertEqual(refresh(c)["sleep"]["sleepTimeSeconds"], 200)


class Availability(unittest.TestCase):
    def setUp(self):
        at(1)

    def failing(self, exc):
        return make(co.GarminCoordinator, Calls({"a": ok(1), "b": ok(2)},
                                                {"a": boom(exc), "b": boom(exc)}))

    def test_one_failed_cycle_keeps_the_data_and_availability(self):
        c = self.failing(api_mod.GarminApiError("down", 503))
        refresh(c)
        at(1, 12, 5)
        data = refresh(c)
        self.assertTrue(c.last_update_success)
        self.assertEqual((data["a"], data["b"]), (1, 2))

    def test_rate_limit_also_keeps_the_data(self):
        c = self.failing(api_mod.GarminRateLimitError("429", 900))
        refresh(c)
        at(1, 12, 5)
        self.assertTrue(refresh(c) and c.last_update_success)

    def test_unavailable_after_the_grace_period(self):
        c = self.failing(api_mod.GarminApiError("down", 503))
        refresh(c)
        at(1, 12, 16)  # 3 x 5 minutes = 15 minutes without success
        refresh(c)
        self.assertFalse(c.last_update_success)

    def test_retry_after_is_passed_on_once_data_is_too_old(self):
        c = make(co.GarminCoordinator, Calls({"a": ok(1)}, {"a": boom(api_mod.GarminRateLimitError("429", 900))}))
        refresh(c)
        at(1, 14)
        with self.assertRaises(stubs.UpdateFailed) as ctx:
            stubs.run(c._async_update_data())
        self.assertEqual(ctx.exception.retry_after, 900)

    def test_first_cycle_failure_is_still_a_failure(self):
        c = make(co.GarminCoordinator, Calls({"a": boom(api_mod.GarminApiError("x")),
                                              "b": boom(api_mod.GarminApiError("y"))}))
        refresh(c)
        self.assertFalse(c.last_update_success)

    def test_daily_group_does_not_hold_yesterdays_data_on_a_new_day(self):
        c = make(co.GarminDailyCoordinator, Calls(
            {"summary": ok(summary("t1"))}, {"summary": boom(api_mod.GarminApiError("x", 503))}))
        refresh(c)
        at(2, 0, 5)
        refresh(c)
        self.assertFalse(c.last_update_success)

    def test_daily_group_holds_within_the_same_day(self):
        c = make(co.GarminDailyCoordinator, Calls(
            {"summary": ok(summary("t1"))}, {"summary": boom(api_mod.GarminApiError("x", 503))}))
        refresh(c)
        at(1, 12, 5)
        data = refresh(c)
        self.assertTrue(c.last_update_success)
        self.assertEqual(data["summary"]["lastSyncTimestampGMT"], "t1")

    def test_auth_error_is_never_held(self):
        c = make(co.GarminCoordinator, Calls({"a": ok(1)}, {"a": boom(api_mod.GarminAuthError("expired"))}))
        refresh(c)
        with self.assertRaises(stubs.ConfigEntryAuthFailed):
            stubs.run(c._async_update_data())


def act(i):
    return {"activityId": i, "activityName": f"A{i}", "activityType": {"typeKey": "running"}}


class ActivityEvents(unittest.TestCase):
    def setUp(self):
        at(1)
        stubs.Store.instances.clear()
        stubs.Store.preset = None

    def coordinator(self, *cycles):
        calls = Calls(*({"activities": ok(a), "wellness_activities": ok([])} for a in cycles))
        return make(co.GarminActivityCoordinator, calls, sticky=("activities",), group="activities")

    def test_activity_found_before_the_entity_exists_is_reported(self):
        stubs.Store.preset = {"last_id": 5}
        c = self.coordinator([act(7), act(6), act(5)])
        refresh(c)  # the first refresh happens before the platform is set up
        entity = ev.GarminActivityEvent(c, stubs.FakeEntry(entry_id="E1"))
        stubs.run(entity.async_added_to_hass())
        self.assertEqual([d["activity_id"] for _, d in entity.triggered], [6, 7])

    def test_nothing_is_reported_twice(self):
        stubs.Store.preset = {"last_id": 5}
        c = self.coordinator([act(6), act(5)], [act(6), act(5)])
        refresh(c)
        entity = ev.GarminActivityEvent(c, stubs.FakeEntry(entry_id="E1"))
        stubs.run(entity.async_added_to_hass())
        refresh(c)
        entity._handle_coordinator_update()
        self.assertEqual([d["activity_id"] for _, d in entity.triggered], [6])

    def test_every_event_writes_the_state(self):
        stubs.Store.preset = {"last_id": 1}
        c = self.coordinator([act(4), act(3), act(2), act(1)])
        refresh(c)
        entity = ev.GarminActivityEvent(c, stubs.FakeEntry(entry_id="E1"))
        stubs.run(entity.async_added_to_hass())
        self.assertEqual([d["activity_id"] for _, d in entity.triggered], [2, 3, 4])
        self.assertEqual(entity.state_writes, 3)

    def test_first_run_ever_reports_nothing(self):
        c = self.coordinator([act(7), act(6)])
        refresh(c)
        entity = ev.GarminActivityEvent(c, stubs.FakeEntry(entry_id="E1"))
        stubs.run(entity.async_added_to_hass())
        self.assertEqual(entity.triggered, [])

    def test_empty_or_failed_first_answer_sets_no_baseline(self):
        full = [act(i) for i in range(20, 0, -1)]
        for first in ([], None):
            stubs.Store.instances.clear()
            c = self.coordinator(first, full)
            refresh(c)
            self.assertEqual([x for i in stubs.Store.instances for x in i.saved], [])
            data = refresh(c)
            self.assertEqual(data["new_activities"], [])  # no flood of 20 events

    def test_failed_activity_call_does_not_set_a_baseline(self):
        full = [act(i) for i in range(20, 0, -1)]
        calls = Calls({"activities": boom(api_mod.GarminApiError("x", 500)), "wellness_activities": ok([])},
                      {"activities": ok(full), "wellness_activities": ok([])})
        c = make(co.GarminActivityCoordinator, calls, sticky=("activities",), group="activities")
        refresh(c)
        self.assertEqual(refresh(c)["new_activities"], [])

    def test_stored_zero_from_an_older_version_counts_as_nothing_seen(self):
        stubs.Store.preset = {"last_id": 0}
        c = self.coordinator([act(i) for i in range(20, 0, -1)])
        self.assertEqual(refresh(c)["new_activities"], [])


class SyncStaleFallback(unittest.TestCase):
    def sensor(self, data):
        from types import SimpleNamespace

        return bs.GarminSyncStaleSensor(SimpleNamespace(data=data), stubs.FakeEntry(entry_id="E1"))

    def setUp(self):
        at(2, 0, 5)

    def test_uses_last_known_sync_after_midnight(self):
        sync = (CLOCK["now"] - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.0")
        s = self.sensor({"summary": {"calendarDate": "2026-05-02"}, "_last_sync": sync})
        self.assertIs(s.is_on, False)

    def test_old_last_known_sync_is_stale(self):
        sync = (CLOCK["now"] - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%S.0")
        s = self.sensor({"summary": None, "_last_sync": sync})
        self.assertIs(s.is_on, True)

    def test_summary_value_wins_over_the_remembered_one(self):
        fresh = (CLOCK["now"] - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.0")
        old = (CLOCK["now"] - timedelta(hours=40)).strftime("%Y-%m-%dT%H:%M:%S.0")
        s = self.sensor({"summary": {"lastSyncTimestampGMT": fresh}, "_last_sync": old})
        self.assertIs(s.is_on, False)

    def test_unknown_when_no_sync_was_ever_seen(self):
        self.assertIsNone(self.sensor({"summary": {}, "_last_sync": None}).is_on)
        self.assertIsNone(self.sensor({"summary": {}}).is_on)


if __name__ == "__main__":
    unittest.main()
