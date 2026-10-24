"""Review fixes in sensor.py, values.py and calendar.py (all numbers are invented examples)."""

import logging
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402

gp = stubs.load_full()
sn = sys.modules["gp_full.sensor"]
cal = sys.modules["gp_full.calendar"]
values = sys.modules["gp_full.values"]
BY = {d.key: d for d in sn.SENSOR_DESCRIPTIONS}


def val(key, data):
    return BY[key].value_fn(data)


def weights(*entries):
    return {"weight": {"dailyWeightSummaries": [{"summaryDate": d, "latestWeight": w} for d, w in entries]}}


class WeightTests(unittest.TestCase):
    def test_profile_edits_are_not_weighings(self):
        data = weights(("2026-10-22", {"weight": 75800, "sourceType": "MANUAL", "bodyFat": 20.0}),
                       ("2026-10-24", {"weight": 78000, "sourceType": "USER_SETTING"}),
                       ("2026-10-23", {"weight": 77000, "sourceType": "change_log"}))
        self.assertEqual(val("weight", data), 75.8)
        self.assertEqual(val("body_fat", data), 20.0)
        self.assertEqual(BY["weight"].attrs_fn(data)["calendar_date"], None)  # entry has no calendarDate
        self.assertEqual(BY["weight"].attrs_fn(data)["source_type"], "MANUAL")

    def test_only_profile_edits_means_no_weight(self):
        data = weights(("2026-10-24", {"weight": 78000, "sourceType": "USER_SETTING"}))
        self.assertIsNone(val("weight", data))
        self.assertIsNone(values.latest_weight(data))

    def test_rule_is_shared_with_values(self):
        self.assertEqual(values.NOT_A_WEIGHING, ("USER_SETTING", "CHANGE_LOG"))
        self.assertTrue(values.is_weighing({"sourceType": "INDEX_SCALE"}))
        self.assertTrue(values.is_weighing({}))
        self.assertFalse(values.is_weighing({"sourceType": "user_setting"}))

    def test_zero_weight_and_bmi_are_no_values(self):
        data = weights(("2026-10-24", {"weight": 0, "bmi": 0.0, "sourceType": "MANUAL"}))
        self.assertIsNone(val("weight", data))
        self.assertIsNone(val("bmi", data))

    def test_zero_decimals_is_an_int(self):
        data = weights(("2026-10-24", {"metabolicAge": 38.4, "sourceType": "MANUAL"}))
        result = val("metabolic_age", data)
        self.assertEqual(result, 38)
        self.assertIsInstance(result, int)

    def test_floors_keep_garmins_value(self):
        # Rounding a running total would make it fall back and look like a reset; the display rounds.
        summary = {"summary": {"floorsAscended": 7.6, "floorsDescended": 3.4, "totalSteps": 1}}
        self.assertEqual(val("floors_ascended", summary), 7.6)
        self.assertEqual(val("floors_descended", summary), 3.4)
        by_key = {d.key: d for d in sn.SENSOR_DESCRIPTIONS}
        self.assertEqual(by_key["floors_ascended"].suggested_display_precision, 0)

    def test_body_masses_in_kg_are_not_rounded_to_two_places(self):
        data = weights(("2026-10-24", {"weight": 75834, "muscleMass": 31234, "boneMass": 3456, "sourceType": "MANUAL"}))
        self.assertEqual(val("weight", data), 75.834)
        self.assertEqual(val("muscle_mass", data), 31.234)
        self.assertEqual(val("bone_mass", data), 3.456)
        by_key = {d.key: d for d in sn.SENSOR_DESCRIPTIONS}
        self.assertEqual(by_key["weight"].suggested_display_precision, 2)


class PlaceholderTests(unittest.TestCase):
    def summary(self, **fields):
        return {"summary": {"totalSteps": 100, **fields}}

    def test_negative_placeholders_are_no_values(self):
        data = self.summary(averageStressLevel=-1, maxStressLevel=-2, totalKilocalories=-18374, activeKilocalories=-5)
        for key in ("stress_average", "stress_max", "total_calories", "active_calories"):
            self.assertIsNone(val(key, data), key)

    def test_real_values_pass(self):
        data = self.summary(averageStressLevel=25, activeKilocalories=300)
        self.assertEqual(val("stress_average", data), 25)
        self.assertEqual(val("active_calories", data), 300)
        self.assertEqual(val("stress_average", self.summary(averageStressLevel=0)), 0)

    def test_negative_altitude_and_remaining_calories_are_real(self):
        data = self.summary(averageMonitoringEnvironmentAltitude=-12, remainingKilocalories=-150)
        self.assertEqual(val("altitude_average", data), -12)
        self.assertEqual(val("remaining_calories", data), -150)

    def test_zero_heart_rate_is_no_measurement(self):
        data = self.summary(minHeartRate=0, restingHeartRate=50, highestRespirationValue=0)
        self.assertIsNone(val("heart_rate_min", data))
        self.assertEqual(val("heart_rate_resting", data), 50)
        self.assertIsNone(val("respiration_highest", data))
        self.assertEqual(val("steps", self.summary(totalSteps=0, restingHeartRate=50)), 0)

    def test_negative_in_other_groups(self):
        self.assertIsNone(val("sleep_stress", {"sleep": {"avgSleepStress": -1}}))
        self.assertIsNone(val("last_activity_calories", {"activities": [{"calories": -1}]}))
        self.assertIsNone(val("last_activity_avg_hr", {"activities": [{"averageHR": 0}]}))

    def test_other_source_days_stay_empty(self):
        self.assertIsNone(val("steps", {"summary": {"source": "fitbit", "totalSteps": 100}}))


class HrvTests(unittest.TestCase):
    def day(self, date, last_night, weekly=None, low=None, status=None):
        return {"calendarDate": date, "lastNightAvg": last_night, "weeklyAvg": weekly, "status": status,
                "baseline": {"lowUpper": low}}

    def test_newest_day_with_night_average_for_value_and_attributes(self):
        data = {"hrv_summaries": [self.day("2026-10-24", None, weekly=60, low=99, status="X"),
                                  self.day("2026-10-23", 45, weekly=50, low=40, status="BALANCED"),
                                  self.day("2026-10-22", 44, weekly=49, low=39)]}
        self.assertEqual(val("hrv_last_night", data), 45)
        self.assertEqual(val("hrv_weekly", data), 50)
        self.assertEqual(val("hrv_status", data), "balanced")
        attrs = BY["hrv_last_night"].attrs_fn(data)
        self.assertEqual(attrs["calendar_date"], "2026-10-23")
        self.assertEqual(attrs["baseline_low_upper"], 40)

    def test_order_of_the_list_does_not_matter(self):
        newest_first = {"hrv_summaries": [self.day("2026-10-24", 48), self.day("2026-10-20", 40)]}
        oldest_first = {"hrv_summaries": list(reversed(newest_first["hrv_summaries"]))}
        self.assertEqual(val("hrv_last_night", newest_first), 48)
        self.assertEqual(val("hrv_last_night", oldest_first), 48)

    def test_no_night_average_means_no_value_and_no_attributes(self):
        data = {"hrv_summaries": [self.day("2026-10-24", None, weekly=60, low=40)]}
        self.assertIsNone(val("hrv_last_night", data))
        self.assertIsNone(val("hrv_weekly", data))
        self.assertIsNone(BY["hrv_last_night"].attrs_fn(data))
        self.assertIsNone(val("hrv_last_night", {}))


class BodyBatteryIndexTests(unittest.TestCase):
    def report(self, descriptors, rows=None):
        return {"body_battery": [{"bodyBatteryValuesArray": rows if rows is not None else [[1000, "MEASURED", 77]],
                                  "bodyBatteryValueDescriptorDTOList": descriptors}]}

    def series(self, data):
        return BY["body_battery"].attrs_fn(data)["values"]

    def test_level_column_is_looked_up(self):
        d = [{"bodyBatteryValueDescriptorKey": "timestamp", "bodyBatteryValueDescriptorIndex": 0},
             {"bodyBatteryValueDescriptorKey": "bodyBatteryStatus", "bodyBatteryValueDescriptorIndex": 1},
             {"bodyBatteryValueDescriptorKey": "bodyBatteryLevel", "bodyBatteryValueDescriptorIndex": 2}]
        self.assertEqual(self.series(self.report(d)), [[1000, 77]])

    def test_index_null_or_missing_descriptor_gives_an_empty_series(self):
        null_index = [{"bodyBatteryValueDescriptorKey": "bodyBatteryLevel", "bodyBatteryValueDescriptorIndex": None}]
        other = [{"bodyBatteryValueDescriptorKey": "timestamp", "bodyBatteryValueDescriptorIndex": 0}]
        self.assertEqual(self.series(self.report(null_index)), [])
        self.assertEqual(self.series(self.report(other)), [])
        self.assertEqual(self.series(self.report(None)), [])
        self.assertEqual(self.series({}), [])


class SleepTests(unittest.TestCase):
    def test_duration_zero_is_no_night(self):
        data = {"sleep": {"sleepTimeSeconds": 0, "deepSleepSeconds": 0, "avgSleepStress": 12,
                          "sleepScores": {"overall": {"value": 70}}}}
        for key in ("sleep_duration", "sleep_deep", "sleep_stress", "sleep_score"):
            self.assertIsNone(val(key, data), key)
        self.assertIsNone(BY["sleep_score"].attrs_fn(data))

    def test_real_night_and_missing_duration(self):
        data = {"sleep": {"sleepTimeSeconds": 25000, "deepSleepSeconds": 0}}
        self.assertEqual(val("sleep_duration", data), 25000)
        self.assertEqual(val("sleep_deep", data), 0)
        self.assertEqual(val("sleep_deep", {"sleep": {"deepSleepSeconds": 100}}), 100)

    def test_naps_and_hrv_do_not_depend_on_the_night(self):
        self.assertEqual(val("nap_duration", {"sleep": {"sleepTimeSeconds": 0, "napTimeSeconds": 900}}), 900)

    def test_sticky_holds_the_last_night(self):
        coord = SimpleNamespace(data={"sleep": {"sleepTimeSeconds": 25000}})
        entity = sn.GarminSensor(coord, stubs.FakeEntry(), BY["sleep_duration"])
        entity._handle_coordinator_update()
        coord.data = {"sleep": {"sleepTimeSeconds": 0}}
        entity._handle_coordinator_update()
        self.assertEqual(entity.native_value, 25000)
        self.assertTrue(entity.extra_state_attributes["held_value"])


class EnumTests(unittest.TestCase):
    def test_garmin_unknown_is_not_the_ha_state(self):
        self.assertIsNone(val("stress_qualifier", {"summary": {"totalSteps": 1, "stressQualifier": "UNKNOWN"}}))
        self.assertEqual(val("stress_qualifier", {"summary": {"totalSteps": 1, "stressQualifier": "CALM"}}), "calm")

    def test_breathing_disruption_is_an_enum_without_invented_values(self):
        description = BY["sleep_breathing_disruption"]
        self.assertEqual(str(description.device_class.value), "enum")
        self.assertEqual(list(description.options), [])
        self.assertIsNone(description.state_class)
        entity = sn.GarminSensor(SimpleNamespace(data={"sleep": {"sleepTimeSeconds": 1, "breathingDisruptionSeverity": "Level_X"}}),
                                 stubs.FakeEntry(), description)
        self.assertEqual(entity.native_value, "level_x")
        self.assertEqual(entity.options, ["level_x"])

    def test_stress_times_are_daily_totals(self):
        for key in ("stress_rest_time", "stress_low_time", "stress_medium_time", "stress_high_time", "highly_active_time"):
            self.assertEqual(BY[key].state_class, sn.TOTAL, key)


class DescriptorTests(unittest.TestCase):
    def test_icons_only_in_icons_json(self):
        self.assertEqual([d.key for d in sn.SENSOR_DESCRIPTIONS if d.icon], [])
        import json
        icons = json.loads((stubs.PKG / "icons.json").read_text())["entity"]["sensor"]
        self.assertGreater(len(icons), 30)
        self.assertTrue(set(icons) <= set(BY) | set(sn.HISTORY_UNITS))

    def test_private_attributes_are_not_recorded(self):
        for name in ("startLatitude", "startLongitude", "locationName", "description", "values", "events"):
            self.assertIn(name, sn.GarminSensor._unrecorded_attributes)

    def test_activity_description_is_shortened(self):
        data = {"activities": [{"activityId": 1, "description": "x" * 1000, "locationName": "Ort"}]}
        attrs = BY["last_activity"].attrs_fn(data)
        self.assertEqual(len(attrs["description"]), sn.ATTRIBUTE_TEXT_LIMIT)
        self.assertEqual(attrs["locationName"], "Ort")


class KeepLastTests(unittest.TestCase):
    def make(self, data=None):
        coord = SimpleNamespace(data=data)
        return coord, sn.GarminSensor(coord, stubs.FakeEntry(), BY["sleep_score"])

    def score(self, value):
        return {"sleep": {"sleepScores": {"overall": {"value": value}}}}

    def test_reading_the_state_has_no_side_effects(self):
        coord, entity = self.make(self.score(80))
        for _ in range(3):
            self.assertEqual(entity.native_value, 80)
            entity.extra_state_attributes  # noqa: B018
            entity.options  # noqa: B018
        self.assertIsNone(entity._last_value)
        self.assertIsNone(entity._last_seen)
        coord.data = {}
        self.assertIsNone(entity.native_value)  # nothing was taken over without an update

    def test_last_seen_changes_only_with_a_new_value(self):
        coord, entity = self.make(self.score(80))
        entity._handle_coordinator_update()
        first = entity._last_seen
        self.assertTrue(first)
        entity._last_seen = "marker"
        entity._handle_coordinator_update()
        self.assertEqual(entity._last_seen, "marker")  # same value again
        coord.data = self.score(81)
        entity._handle_coordinator_update()
        self.assertNotEqual(entity._last_seen, "marker")
        self.assertFalse(entity.extra_state_attributes["held_value"])

    def test_restore_after_restart_keeps_value_when_nothing_is_delivered(self):
        coord, entity = self.make(None)
        entity._stored = SimpleNamespace(native_value=77)
        entity._stored_state = SimpleNamespace(state="77", attributes={"last_seen": "2026-10-24T05:00:00+00:00"})
        stubs.run(entity.async_added_to_hass())
        self.assertEqual(entity.native_value, 77)
        attrs = entity.extra_state_attributes
        self.assertTrue(attrs["held_value"])
        self.assertEqual(attrs["last_seen"], "2026-10-24T05:00:00+00:00")

    def test_restore_from_unavailable_state_has_no_last_seen(self):
        coord, entity = self.make(None)
        entity._stored = SimpleNamespace(native_value=77)
        entity._stored_state = SimpleNamespace(state="unavailable", attributes={"last_seen": "stale"})
        stubs.run(entity.async_added_to_hass())
        self.assertEqual(entity.native_value, 77)
        self.assertIsNone(entity.extra_state_attributes["last_seen"])

    def test_restored_value_is_replaced_by_a_new_one(self):
        coord, entity = self.make(self.score(90))
        entity._stored = SimpleNamespace(native_value=77)
        entity._stored_state = SimpleNamespace(state="77", attributes={"last_seen": "old"})
        stubs.run(entity.async_added_to_hass())
        self.assertEqual(entity.native_value, 90)
        self.assertNotEqual(entity._last_seen, "old")


class KeyExpiryTests(unittest.TestCase):
    def test_available_and_local(self):
        entry = stubs.FakeEntry(data={"key_expires_at": "2026-12-01T00:00:00+00:00"})
        entity = sn.GarminKeyExpirySensor(entry)
        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value, datetime(2026, 12, 1, tzinfo=UTC))
        self.assertIsNone(sn.GarminKeyExpirySensor(stubs.FakeEntry()).native_value)
        self.assertFalse(hasattr(entity, "coordinator"))


class PruneTests(unittest.TestCase):
    NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    DATA = {
        "daily": {"summary": {"totalSteps": 5, "lastSyncTimestampGMT": "2026-10-24T06:00:00.0"}},
        "sleep": {"sleep": {"sleepTimeSeconds": 100}},
        "body": {"weight": {"dailyWeightSummaries": [{"summaryDate": "2026-10-20",
                                                     "latestWeight": {"weight": 80000, "sourceType": "MANUAL"}}]}},
    }

    def prune(self, data=None, created=None, now=None):
        return sn.sensors_to_prune(data or self.DATA, created, now or self.NOW)

    def test_decision_when_all_conditions_hold(self):
        with self.assertLogs(sn._LOGGER, "INFO") as logs:
            keys = self.prune(created=self.NOW - timedelta(days=2))
        self.assertIn("bmi", keys)
        self.assertIn("body_fat", keys)
        self.assertNotIn("weight", keys)
        self.assertIn("Disabling", logs.output[-1])
        self.assertIn("bmi", logs.output[-1])

    def test_daily_and_sleep_values_are_never_disabled(self):
        keys = self.prune(created=self.NOW - timedelta(days=2))
        self.assertFalse({k for k in keys if BY[k].group in ("daily", "sleep")})
        self.assertNotIn("sleep_score", keys)
        self.assertNotIn("heart_rate_resting", keys)

    def test_activity_sensors_are_never_disabled_by_one_activity_without_heart_rate_or_distance(self):
        data = {**self.DATA, "activities": {"activities": [{"activityId": 1, "calories": 300.0,
                                                           "activityType": {"typeKey": "strength_training"}}]}}
        self.assertEqual(sn.PRUNE_SKIP_GROUPS & {"activities"}, {"activities"})
        keys = self.prune(data, created=self.NOW - timedelta(days=2))
        self.assertFalse({k for k in keys if k.startswith("last_activity") or k == "wellness_activities"})
        # the same activity does leave these values empty, which is what used to switch them off
        self.assertIsNone(BY["last_activity_avg_hr"].value_fn(data["activities"]))
        self.assertIsNone(BY["last_activity_distance"].value_fn(data["activities"]))
        self.assertIn("bmi", keys)  # body sensors are still decided as before

    def test_young_entry_waits(self):
        with self.assertLogs(sn._LOGGER, "INFO") as logs:
            self.assertEqual(self.prune(created=self.NOW - timedelta(hours=23)), set())
        self.assertIn("less than 24 hours", logs.output[-1])
        self.assertIsNone(sn.prune_blocker(self.DATA, self.NOW - timedelta(hours=24), self.NOW))

    def test_unknown_age_waits(self):
        self.assertEqual(self.prune(created=None), set())
        self.assertIsNotNone(sn.prune_blocker(self.DATA, None, self.NOW))

    def test_no_sync_today_waits(self):
        old = {**self.DATA, "daily": {"summary": {"totalSteps": 5, "lastSyncTimestampGMT": "2026-10-23T22:00:00.0"}}}
        self.assertEqual(self.prune(old, self.NOW - timedelta(days=2)), set())
        self.assertIn("synchronised", sn.prune_blocker(old, self.NOW - timedelta(days=2), self.NOW))
        self.assertIsNotNone(sn.prune_blocker({}, self.NOW - timedelta(days=2), self.NOW))

    def test_naive_creation_time_is_treated_as_utc(self):
        self.assertIsNone(sn.prune_blocker(self.DATA, datetime(2026, 10, 20), self.NOW))


class CalendarTests(unittest.TestCase):
    START = "2026-10-01 06:00:00"

    def event(self, hass=None, **extra):
        return cal.activity_event({"activityId": 1, "startTimeGMT": self.START, "duration": 3600.0, **extra}, hass)

    def test_decimal_comma_by_language_and_readable_fallback_title(self):
        de = SimpleNamespace(config=SimpleNamespace(language="de"))
        en = SimpleNamespace(config=SimpleNamespace(language="en"))
        self.assertEqual(self.event(de, distance=10250.0).description, "10,25 km")
        self.assertEqual(self.event(en, distance=10250.0).description, "10.25 km")
        self.assertEqual(self.event(activityType={"typeKey": "trail_running"}).summary, "Trail running")
        self.assertEqual(self.event().summary, "Garmin")
        self.assertEqual(self.event(activityName="Morgenrunde").summary, "Morgenrunde")

    def test_end_uses_elapsed_duration_when_longer(self):
        ev = self.event(elapsedDuration=4000.0)
        self.assertEqual(ev.end - ev.start, timedelta(seconds=4000))

    def test_end_falls_back_to_duration(self):
        for extra in ({}, {"elapsedDuration": None}, {"elapsedDuration": 100.0}, {"elapsedDuration": "x"}):
            ev = self.event(**extra)
            self.assertEqual(ev.end - ev.start, timedelta(hours=1), extra)

    def test_distance_follows_home_assistant_units(self):
        imperial = SimpleNamespace(config=SimpleNamespace(units=SimpleNamespace(
            length=lambda value, unit: value / 1609.344, length_unit="mi")))
        metric = SimpleNamespace(config=SimpleNamespace(units=SimpleNamespace(
            length=lambda value, unit: value / 1000, length_unit="km")))
        self.assertEqual(self.event(imperial, distance=16093.44).description, "10.00 mi")
        self.assertEqual(self.event(metric, distance=10000.0).description, "10.00 km")
        self.assertEqual(self.event(None, distance=10000.0, calories=300).description, "10.00 km, 300 kcal")

    def entity(self, activities):
        return cal.GarminActivityCalendar(SimpleNamespace(data={"activities": activities}), stubs.FakeEntry())

    def activity(self, i, start, duration=3600.0):
        return {"activityId": i, "startTimeGMT": start.strftime("%Y-%m-%d %H:%M:%S"), "duration": duration}

    def test_event_is_running_or_upcoming_never_finished(self):
        now = datetime.now(UTC)
        past = self.activity(1, now - timedelta(days=2))
        self.assertIsNone(self.entity([past]).event)
        running = self.activity(2, now - timedelta(minutes=10))
        self.assertEqual(self.entity([past, running]).event.uid, "2")
        later = self.activity(3, now + timedelta(days=1))
        sooner = self.activity(4, now + timedelta(hours=1))
        self.assertEqual(self.entity([past, later, sooner]).event.uid, "4")


if __name__ == "__main__":
    logging.disable(logging.NOTSET)
    unittest.main()
