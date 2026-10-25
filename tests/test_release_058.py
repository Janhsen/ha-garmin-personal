"""Release 0.5.8: raw fetch parameters, error texts, number-string timestamps, fitness age shapes, new sensors."""

import json
import sys
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _load import load  # noqa: E402
from test_api import TOKEN_PATH, FakeSession, Resp, jwt, make, run  # noqa: E402
from test_sensors import load_sensor  # noqa: E402

gp = load()
api = gp.api
v = gp.values

DAY = date(2026, 10, 1)


def recording(client):
    seen = []

    async def fake_request(path, params=None, **kw):
        seen.append((path, list(params or [])))
        return {}

    client._request = fake_request
    return seen


class RawFetchParameters(unittest.TestCase):
    def test_defaults_are_the_requests_of_the_sensors(self):
        c = make(FakeSession())
        seen = recording(c)
        run(c.fetch("body_battery", day=DAY, start=DAY, end=DAY))
        run(c.fetch("fitness_age", day=DAY))
        run(c.fetch("weight_range", start=DAY, end=DAY))
        self.assertEqual(dict(seen[0][1]), {"startDate": "2026-10-01", "endDate": "2026-10-01"})
        self.assertEqual(dict(seen[1][1]), {"fullHistoryScan": "false"})
        self.assertEqual(dict(seen[2][1]), {"includeAll": "true"})

    def test_chunks_full_history_scan_include_all_are_sent(self):
        c = make(FakeSession())
        seen = recording(c)
        run(c.fetch("body_battery", start=DAY, end=DAY, chunks=96))
        run(c.fetch("fitness_age", day=DAY, full_history_scan=True))
        run(c.fetch("weight_range", start=DAY, end=DAY, include_all=False))
        self.assertIn(("chunks", "96"), seen[0][1])
        self.assertEqual(dict(seen[1][1]), {"fullHistoryScan": "true"})
        self.assertEqual(dict(seen[2][1]), {"includeAll": "false"})

    def test_other_endpoints_ignore_them(self):
        c = make(FakeSession())
        seen = recording(c)
        run(c.fetch("steps", start=DAY, end=DAY, chunks=5, full_history_scan=True, include_all=True))
        self.assertEqual(dict(seen[0][1]), {})  # the path carries the dates; no extra parameter


class ErrorTexts(unittest.TestCase):
    def failing(self, status, body, path="/activitylist-service/activities/search/activities", headers=None):
        s = FakeSession()
        tok = jwt(datetime.now(UTC) + timedelta(hours=24))
        s.add("POST", TOKEN_PATH, Resp(200, f'"{tok}"'))
        s.add("GET", path, Resp(status, body, headers))
        c = make(s)
        with self.assertRaises(api.GarminApiError) as ctx:
            run(c._request(path))
        return ctx.exception, tok

    def test_400_carries_garmins_reason(self):
        err, _ = self.failing(400, json.dumps({"message": "Unknown activityType 'runing'"}))
        self.assertEqual(err.status, 400)
        self.assertIn("(HTTP 400): Unknown activityType 'runing'", str(err))

    def test_plain_text_body(self):
        err, _ = self.failing(400, "Bounding box too large")
        self.assertTrue(str(err).endswith(": Bounding box too large"))

    def test_shortened_to_200_characters(self):
        err, _ = self.failing(400, "x y " * 200)
        detail = str(err).split("): ", 1)[1]
        self.assertLessEqual(len(detail), api.ERROR_DETAIL_MAX)
        self.assertTrue(detail.endswith("…"))

    def test_no_tokens_keys_or_headers(self):
        s = FakeSession()
        tok = jwt(datetime.now(UTC) + timedelta(hours=24))
        s.add("POST", TOKEN_PATH, Resp(200, f'"{tok}"'))
        body = f"bad request; Authorization: Bearer {tok}; ApiKey KEY; key KEY; token {tok}"
        s.add("GET", "/x", Resp(400, body))
        c = make(s)
        with self.assertRaises(api.GarminApiError) as ctx:
            run(c._request("/x"))
        text = str(ctx.exception)
        self.assertNotIn(tok, text)
        self.assertNotIn("KEY", text)
        self.assertNotIn("Bearer", text)
        self.assertIn("bad request", text)

    def test_html_or_empty_body_adds_nothing(self):
        err, _ = self.failing(400, "<html>blocked</html>")
        self.assertEqual(str(err), "GET /activitylist-service/activities/search/activities failed (HTTP 400)")
        err, _ = self.failing(400, "x", headers={"Content-Type": "text/html"})
        self.assertNotIn(":", str(err).split("(HTTP 400)")[1])
        err, _ = self.failing(400, "")
        self.assertTrue(str(err).endswith("(HTTP 400)"))

    def test_404_of_an_activity(self):
        err, _ = self.failing(404, "", path="/activity-service/activity/5")
        self.assertEqual(err.status, 404)
        self.assertIn("no activity with this id", str(err))
        err, _ = self.failing(404, '{"message": "Activity 5 not found"}', path="/activity-service/activity/5")
        self.assertIn("Activity 5 not found", str(err))

    def test_other_statuses_stay_short(self):
        err, _ = self.failing(404, "some page", path="/hrv-service/hrv/2026-10-01")
        self.assertTrue(str(err).endswith("(HTTP 404)"))
        err, _ = self.failing(403, "denied by policy", path="/hrv-service/hrv/2026-10-01")
        self.assertTrue(str(err).endswith("(HTTP 403)"))

    def test_error_detail_helper(self):
        self.assertEqual(api.error_detail(None), "")
        self.assertEqual(api.error_detail(b'{"error": "bad", "message": "worse"}'), "worse; bad")
        self.assertEqual(api.error_detail('"just text"'), "just text")
        self.assertEqual(api.error_detail("a\nb\tc\x00d"), "a b c d")


class TimestampStrings(unittest.TestCase):
    def test_epoch_milliseconds_as_text(self):
        expected = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        self.assertEqual(v.parse_timestamp("1700000000000"), expected)
        self.assertEqual(v.parse_timestamp(" 1700000000000.0 "), expected)
        self.assertEqual(v.parse_timestamp(1700000000000), expected)

    def test_other_strings_unchanged(self):
        self.assertEqual(v.parse_timestamp("2026-10-24T06:00:00.0"), datetime(2026, 10, 24, 6, tzinfo=UTC))
        self.assertEqual(v.parse_timestamp("2026-10-24 05:00:00"), datetime(2026, 10, 24, 5, tzinfo=UTC))
        self.assertIsNone(v.parse_timestamp("1700000000"))
        self.assertIsNone(v.parse_timestamp("abc"))
        self.assertIsNone(v.parse_timestamp(True))

    def test_timestamp_at_reads_text(self):
        got = v.timestamp_at("sleep", "sleepStartTimestampGMT")({"sleep": {"sleepStartTimestampGMT": "1700000000000"}})
        self.assertEqual(got, datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC))


class FitnessAgeShapes(unittest.TestCase):
    OBJECT = {"fitnessAge": 31.44, "achievableFitnessAge": 28.0, "chronologicalAge": 38,
              "previousFitnessAge": 32.1, "lastUpdated": "2026-10-20T06:00:00", "components": {"rhr": {"value": 50}}}

    @classmethod
    def setUpClass(cls):
        cls.sensor = load_sensor()
        cls.by = {d.key: d for d in cls.sensor.SENSOR_DESCRIPTIONS}

    def read(self, raw):
        data = {"fitness_age": raw}
        return {k: self.by[k].value_fn(data) for k in ("fitness_age", "fitness_age_achievable", "chronological_age")}, \
            self.by["fitness_age"].attrs_fn(data)

    def test_object(self):
        values, attrs = self.read(self.OBJECT)
        self.assertEqual(values, {"fitness_age": 31.4, "fitness_age_achievable": 28.0, "chronological_age": 38})
        self.assertEqual(attrs["previous_fitness_age"], 32.1)
        self.assertEqual(attrs["components"], {"rhr": {"value": 50}})

    def test_array_takes_newest_record_with_a_value(self):
        older = {**self.OBJECT, "fitnessAge": 33.0, "lastUpdated": "2026-09-01T06:00:00"}
        newer = {**self.OBJECT, "fitnessAge": 30.0}
        empty = {"invalidReason": "USER_EMPTY_AGE", "lastUpdated": "2026-10-25T06:00:00"}
        values, attrs = self.read([older, newer, empty])
        self.assertEqual(values["fitness_age"], 30.0)
        self.assertEqual(attrs["previous_fitness_age"], 32.1)
        values, _ = self.read([newer, older])  # order does not matter when times can be read
        self.assertEqual(values["fitness_age"], 30.0)

    def test_array_without_readable_times_takes_the_last_one(self):
        a, b = {"fitnessAge": 40.0}, {"fitnessAge": 39.0}
        self.assertEqual(self.read([a, b])[0]["fitness_age"], 39.0)

    def test_only_invalid_records_keep_the_reason(self):
        values, attrs = self.read([{"invalidReason": "USER_UNDER_AGE"}])
        self.assertIsNone(values["fitness_age"])
        self.assertEqual(attrs["invalid_reason"], "USER_UNDER_AGE")

    def test_no_data_and_junk(self):
        for raw in (None, [], "x", 5, [1, "a"], {}):
            values, _ = self.read(raw)
            self.assertIsNone(values["fitness_age"], raw)
        self.assertIsNone(self.by["fitness_age"].attrs_fn({}))
        self.assertIsNone(self.by["fitness_age"].attrs_fn({"fitness_age": []}))

    def test_previous_fitness_age_missing_is_left_out(self):
        _, attrs = self.read({"fitnessAge": 30.0})
        self.assertNotIn("previous_fitness_age", attrs)


class NewSensors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sensor = load_sensor()
        cls.by = {d.key: d for d in cls.sensor.SENSOR_DESCRIPTIONS}

    def test_speed_sensors_m_per_s_shown_as_km_per_h(self):
        for key, field in (("last_activity_avg_speed", "averageSpeed"), ("last_activity_max_speed", "maxSpeed")):
            d = self.by[key]
            self.assertEqual(d.native_unit_of_measurement, "meters_per_second")
            self.assertEqual(d.suggested_unit_of_measurement, "kilometers_per_hour")
            self.assertEqual(d.device_class, self.sensor.SensorDeviceClass.SPEED)
            self.assertFalse(d.entity_registry_enabled_default)
            self.assertIsNone(d.state_class)
            data = {"activities": [{field: 2.5}]}
            self.assertEqual(d.value_fn(data), 2.5)  # raw m/s: Home Assistant converts for display
            self.assertIsNone(d.value_fn({"activities": [{field: 0}]}))
            self.assertIsNone(d.value_fn({"activities": []}))

    def test_existing_sensors_have_no_suggested_unit(self):
        for d in self.sensor.SENSOR_DESCRIPTIONS:
            if not d.key.endswith("_speed"):
                self.assertIsNone(d.suggested_unit_of_measurement, d.key)

    def test_vo2max_has_its_unit(self):
        self.assertEqual(self.by["last_activity_vo2max"].native_unit_of_measurement, "ml/kg/min")

    def test_heart_rate_alerts(self):
        d = self.by["heart_rate_alerts"]
        self.assertFalse(d.entity_registry_enabled_default)
        data = {"summary": {"source": "GARMIN", "abnormalHeartRateAlertsCount": 0},
                "heart_rate": {"abnormalHrThresholdValue": 160, "lowAbnormalHrThresholdValue": 40}}
        self.assertEqual(d.value_fn(data), 0)  # no alert is a real zero
        self.assertEqual(d.attrs_fn(data), {"high_threshold": 160, "low_threshold": 40})
        self.assertIsNone(d.attrs_fn({"summary": {}}))  # heart rate answer not requested: no thresholds
        self.assertIsNone(d.value_fn({"summary": {"source": "fitbit", "abnormalHeartRateAlertsCount": 3}}))
        self.assertIsNone(d.value_fn({}))

    def test_activity_attributes(self):
        zones = {f"hrTimeInZone_{n}": 10.5 * n for n in range(1, 6)}
        splits = {"fastestSplit_1000": 250.0, "fastestSplit_5000": 1300.0}
        attrs = self.by["last_activity"].attrs_fn({"activities": [{"activityId": 1, **zones, **splits, "other": 1}]})
        for key, value in {**zones, **splits}.items():
            self.assertEqual(attrs[key], value)
        self.assertNotIn("fastestSplit_10000", attrs)  # not in the answer: not invented
        self.assertNotIn("other", attrs)
        self.assertLess(len(json.dumps(attrs)), 16 * 1024)

    def test_hr_zone_floors_already_exist_as_attributes(self):
        attrs = self.by["hr_max_used"].attrs_fn({"hr_zones": [{"sport": "DEFAULT", "zone1Floor": 100, "zone5Floor": 170}]})
        self.assertEqual((attrs["zone_1_floor"], attrs["zone_5_floor"]), (100, 170))


if __name__ == "__main__":
    unittest.main()
