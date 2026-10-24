"""Build the sensor list against stubbed Home Assistant modules and run every value function."""

import enum
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _load import PKG, load  # noqa: E402


def stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


class Anything:
    def __init__(self, *a, **k):
        pass

    def __class_getitem__(cls, item):
        return cls

    def __getattr__(self, name):
        return Anything()


def distinct(name):
    return type(name, (Anything,), {})


class Enum(str, enum.Enum):
    pass


def make_enum(name, *members):
    return Enum(name, {m: m.lower() for m in members})


@dataclass(frozen=True, kw_only=True)
class SensorEntityDescription:
    key: str
    translation_key: str | None = None
    native_unit_of_measurement: str | None = None
    device_class: object = None
    state_class: object = None
    entity_registry_enabled_default: bool = True
    entity_category: object = None
    icon: str | None = None
    suggested_display_precision: int | None = None
    options: object = None


def install_stubs():
    dc = make_enum("SensorDeviceClass", "DISTANCE", "DURATION", "ENUM", "TIMESTAMP", "VOLUME", "WEIGHT")
    sc = make_enum("SensorStateClass", "MEASUREMENT", "TOTAL", "TOTAL_INCREASING")
    stub("homeassistant")
    stub("homeassistant.components")
    stub("homeassistant.components.sensor", SensorDeviceClass=dc, SensorStateClass=sc,
         SensorEntity=distinct('SensorEntity'), RestoreSensor=distinct('RestoreSensor'), SensorEntityDescription=SensorEntityDescription)
    stub("homeassistant.const", PERCENTAGE="%",
         EntityCategory=make_enum("EntityCategory", "DIAGNOSTIC", "CONFIG"),
         UnitOfLength=make_enum("UnitOfLength", "METERS"), UnitOfMass=make_enum("UnitOfMass", "KILOGRAMS"),
         UnitOfTime=make_enum("UnitOfTime", "MINUTES", "SECONDS", "YEARS"),
         UnitOfVolume=make_enum("UnitOfVolume", "MILLILITERS"))
    stub("homeassistant.core", HomeAssistant=Anything, callback=lambda f: f)
    stub("homeassistant.helpers")
    stub("homeassistant.helpers.entity_platform", AddEntitiesCallback=Anything)
    stub("homeassistant.helpers.typing", StateType=object)
    stub("homeassistant.helpers.device_registry", DeviceEntryType=make_enum("D", "SERVICE"), DeviceInfo=dict)
    stub("homeassistant.config_entries", ConfigEntry=Anything)
    stub("homeassistant.helpers.issue_registry")
    stub("homeassistant.helpers.storage", Store=Anything)
    stub("homeassistant.helpers.update_coordinator", CoordinatorEntity=distinct('CoordinatorEntity'),
         DataUpdateCoordinator=distinct('DataUpdateCoordinator'), UpdateFailed=Exception)
    stub("homeassistant.exceptions", ConfigEntryAuthFailed=Exception)
    stub("homeassistant.util")
    stub("homeassistant.util.dt")
    from datetime import datetime as _dt
    from datetime import UTC as _UTC

    sys.modules["homeassistant.util.dt"].now = lambda: _dt.now(_UTC).astimezone()
    sys.modules["homeassistant.util.dt"].utcnow = lambda: _dt.now(_UTC)
    sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]
    sys.modules["homeassistant.helpers"].issue_registry = sys.modules["homeassistant.helpers.issue_registry"]


def load_sensor():
    pkg = load()
    install_stubs()
    for mod in ("repairs", "coordinator", "entity", "sensor"):
        spec = importlib.util.spec_from_file_location(f"{pkg.__name__}.{mod}", PKG / f"{mod}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg.__name__}.{mod}"] = module
        spec.loader.exec_module(module)
        setattr(pkg, mod, module)
    return pkg.sensor


DATA = {
    "daily": {
        "summary": {"totalSteps": 8123, "dailyStepGoal": 10000, "totalDistanceMeters": 6400.5, "totalKilocalories": 2400,
                    "restingHeartRate": 52, "averageStressLevel": 31, "stressQualifier": "BALANCED",
                    "bodyBatteryMostRecentValue": 64, "floorsAscended": 7.6, "lastSyncTimestampGMT": "2026-10-24T06:00:00.0"},
        "spo2": {"averageSpO2": 95, "lowestSpO2": 90, "spO2HourlyAverages": [[1700000000000, 95]]},
        "hydration": [{"valueInML": 1500, "goalInML": 2800}],
        "body_battery": [{"bodyBatteryValuesArray": [[1700000000000, 50]],
                          "bodyBatteryValueDescriptorDTOList": [{"bodyBatteryValueDescriptorKey": "timestamp", "index": 0},
                                                                 {"bodyBatteryValueDescriptorKey": "bodyBatteryLevel", "index": 1}]}],
        "heart_rate": {"heartRateValues": [[1700000000000, 60], [1700000060000, None]]},
    },
    "sleep": {
        "sleep": {"sleepTimeSeconds": 27000, "deepSleepSeconds": 5000, "sleepScores": {"overall": {"value": 81, "qualifierKey": "GOOD"}},
                  "sleepStartTimestampGMT": 1700000000000, "sleepNeed": {"actual": 480}},
        "hrv_summaries": [{"lastNightAvg": 48, "weeklyAvg": 50, "status": "BALANCED", "baseline": {"lowUpper": 40, "balancedLow": 41}}],
    },
    "body": {
        "weight": {"dailyWeightSummaries": [{"summaryDate": "2026-10-20", "latestWeight": {"weight": 80500.0, "bodyFat": 18.2, "muscleMass": 35000}}]},
        "fitness_age": {"fitnessAge": 31.4, "chronologicalAge": 38},
    },
    "activities": {
        "activities": [{"activityId": 1, "activityName": "Morning Run", "activityType": {"typeKey": "running"},
                        "startTimeGMT": "2026-10-24 05:00:00", "distance": 10000.0, "duration": 3000.0, "averageHR": 150.0}],
        "wellness_activities": [{}, {}],
    },
    "profile": {"profile": {"displayName": "example-user", "measurementSystem": "metric"},
                "hr_zones": [{"sport": "DEFAULT", "maxHeartRateUsed": 185, "zone1Floor": 100}]},
}


class SensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sensor = load_sensor()

    def test_keys_unique(self):
        keys = [d.key for d in self.sensor.SENSOR_DESCRIPTIONS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertGreater(len(keys), 100)

    def test_groups_known(self):
        self.assertTrue({d.group for d in self.sensor.SENSOR_DESCRIPTIONS} <= set(DATA))

    def test_all_value_functions_run_on_data_and_on_empty(self):
        for d in self.sensor.SENSOR_DESCRIPTIONS:
            d.value_fn(DATA[d.group])
            d.value_fn({})
            if d.attrs_fn:
                d.attrs_fn(DATA[d.group])
                d.attrs_fn({})

    def test_new_garmin_fields(self):
        by = {d.key: d for d in self.sensor.SENSOR_DESCRIPTIONS}
        daily = {"summary": {"source": "GARMIN", "totalSteps": 100, "stressPercentage": 29.09, "lowStressPercentage": 23.38,
                             "averageMonitoringEnvironmentAltitude": 345, "highestRespirationValue": 21,
                             "minAvgHeartRate": 43, "maxAvgHeartRate": 112,
                             "bodyBatteryDynamicFeedbackEvent": {"bodyBatteryLevel": "HIGH", "feedbackShortType": "X",
                                                                 "eventTimestampGmt": "t"},
                             "bodyBatteryActivityEventList": [{"eventType": "SLEEP", "bodyBatteryImpact": 60}]}}
        v = lambda k, d: by[k].value_fn(d)  # noqa: E731
        self.assertEqual(v("stress_percentage", daily), 29.09)
        self.assertEqual(v("stress_low_percentage", daily), 23.38)
        self.assertEqual(v("altitude_average", daily), 345)
        self.assertEqual(v("respiration_highest", daily), 21)
        self.assertEqual(v("heart_rate_avg_min", daily), 43)
        self.assertEqual(v("body_battery_level", daily), "high")
        attrs = by["body_battery_level"].attrs_fn(daily)
        self.assertEqual(attrs["events"][0]["bodyBatteryImpact"], 60)
        self.assertEqual(attrs["feedback"]["bodyBatteryLevel"], "HIGH")
        sleep = {"sleep": {"sleepAlignment": {"status": "BEHIND", "optimalSleepWindowStartMins": -80},
                           "sleepNeed": {"recommendedBedtimeStartMins": 1410}}}
        self.assertEqual(v("sleep_alignment", sleep), "behind")
        self.assertEqual(by["sleep_alignment"].attrs_fn(sleep),
                         {"optimal_window_start_min": -80, "recommended_bedtime_start_min": 1410})
        self.assertIsNone(v("sleep_alignment", {}))
        self.assertIsNone(by["body_battery_level"].attrs_fn({}))

    def test_values(self):
        by = {d.key: d for d in self.sensor.SENSOR_DESCRIPTIONS}
        val = lambda k: by[k].value_fn(DATA[by[k].group])  # noqa: E731
        self.assertEqual(val("steps"), 8123)
        self.assertEqual(val("weight"), 80.5)
        self.assertEqual(val("muscle_mass"), 35.0)
        self.assertEqual(val("sleep_score"), 81)
        self.assertEqual(val("hrv_last_night"), 48)
        self.assertEqual(val("hydration"), 1500)
        self.assertEqual(val("last_activity"), "Morning Run")
        self.assertEqual(val("hr_max_used"), 185)
        self.assertEqual(val("floors_ascended"), 8)
        self.assertEqual(val("wellness_activities"), 2)
        self.assertEqual(val("last_sync").year, 2026)
        self.assertEqual(by["body_battery"].attrs_fn(DATA["daily"])["values"], [[1700000000000, 50]])
        self.assertEqual(by["sleep_score"].attrs_fn(DATA["sleep"])["qualifierKey"], "GOOD")


class PruneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sensor = load_sensor()

    NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    OLD = NOW - timedelta(days=3)

    def prune(self, data):
        return self.sensor.sensors_to_prune(data, self.OLD, self.NOW)

    def synced(self, data):
        data = {k: dict(v) for k, v in data.items()}
        data["daily"]["summary"] = {**data["daily"]["summary"], "lastSyncTimestampGMT": "2026-10-24T06:00:00.0"}
        return data

    def test_prunes_only_empty_body_and_activity_fields_of_answered_endpoints(self):
        data = self.synced(DATA)
        pruned = self.prune(data)
        # weight answered: BMI is empty -> pruned; body fat has a value -> kept
        self.assertIn("bmi", pruned)
        self.assertNotIn("body_fat", pruned)
        self.assertNotIn("weight", pruned)
        # daily and sleep values can still appear later in the day: never disabled automatically
        by = {d.key: d for d in self.sensor.SENSOR_DESCRIPTIONS}
        self.assertFalse({k for k in pruned if by[k].group in ("daily", "sleep")})
        self.assertNotIn("active_calories", pruned)

    def test_nothing_pruned_without_data(self):
        self.assertEqual(self.prune({}), set())
        self.assertEqual(self.prune({"daily": {}}), set())

    def test_hidden_by_default_and_diagnostics_untouched(self):
        pruned = self.prune(self.synced(DATA))
        by = {d.key: d for d in self.sensor.SENSOR_DESCRIPTIONS}
        for key in pruned:
            self.assertTrue(by[key].entity_registry_enabled_default)
            self.assertIsNone(by[key].entity_category)


class CallBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_sensor()
        cls.coordinator = sys.modules["gp_under_test.coordinator"]

    def test_intraday_endpoints_only_when_enabled(self):
        from datetime import date

        off = self.coordinator.make_daily_calls(False)(None, date(2026, 10, 24))
        on = self.coordinator.make_daily_calls(True)(None, date(2026, 10, 24))
        self.assertEqual(set(off), {"summary", "spo2", "hydration"})
        self.assertEqual(set(on), {"summary", "spo2", "hydration", "heart_rate", "body_battery"})

    def test_unused_endpoints_are_not_requested(self):
        from datetime import date

        today = date(2026, 10, 24)
        calls = {}
        for builder in (self.coordinator.sleep_calls, self.coordinator.body_calls,
                        self.coordinator.activity_calls, self.coordinator.profile_calls):
            calls.update(builder(None, today))
        self.assertNotIn("hrv", calls)
        self.assertNotIn("weight_goals", calls)
        self.assertIn("hrv_summaries", calls)


class SyncGatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_sensor()
        cls.coordinator = sys.modules["gp_under_test.coordinator"]

    def make(self, sync_values):
        """A daily coordinator whose summary reports successive sync times."""
        import asyncio

        c = self.coordinator.GarminDailyCoordinator.__new__(self.coordinator.GarminDailyCoordinator)
        counts = {"summary": 0, "spo2": 0, "hydration": 0, "refresh": 0}
        syncs = iter(sync_values)

        async def summary():
            counts["summary"] += 1
            return {"lastSyncTimestampGMT": next(syncs), "totalSteps": 1}

        async def spo2():
            counts["spo2"] += 1
            return {"averageSpO2": 95}

        async def hydration():
            counts["hydration"] += 1
            return [{"valueInML": 1}]

        class Follower:
            async def async_request_refresh(self_inner):
                counts["refresh"] += 1

        class Hass:
            def async_create_task(self_inner, coro):
                asyncio.get_event_loop().create_task(coro)

        c.group, c.api, c._sticky, c._warned = "daily", None, (), set()
        c._build_calls = lambda api, today: {"summary": summary, "spo2": spo2, "hydration": hydration}
        c.data = {}
        c.hass = Hass()
        c.followers = [Follower(), Follower()]
        c._last_sync = None
        c._last_full = None
        return c, counts

    def cycle(self, c):
        import asyncio

        async def run():
            c.data = await c._async_update_data()
            await asyncio.sleep(0)  # let follower refresh tasks run
            await asyncio.sleep(0)

        asyncio.run(run())

    def test_unchanged_sync_asks_only_for_summary(self):
        c, n = self.make(["t1", "t1", "t1"])
        self.cycle(c)
        self.assertEqual((n["summary"], n["spo2"], n["hydration"]), (1, 1, 1))  # first run: everything
        self.cycle(c)
        self.cycle(c)
        self.assertEqual((n["summary"], n["spo2"], n["hydration"]), (3, 1, 1))
        self.assertEqual(n["refresh"], 0)
        self.assertEqual(c.data["spo2"], {"averageSpO2": 95})  # carried over

    def test_new_sync_fetches_everything_and_wakes_followers(self):
        c, n = self.make(["t1", "t2"])
        self.cycle(c)
        self.cycle(c)
        self.assertEqual((n["summary"], n["spo2"], n["hydration"]), (2, 2, 2))
        self.assertEqual(n["refresh"], 2)

    def test_hourly_fallback(self):
        from datetime import timedelta

        c, n = self.make(["t1", "t1"])
        self.cycle(c)
        c._last_full = c._last_full - timedelta(minutes=61)
        self.cycle(c)
        self.assertEqual((n["spo2"], n["hydration"]), (2, 2))
        self.assertEqual(n["refresh"], 0)  # no new sync -> followers not woken


class LabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sensor = load_sensor()
        cls.labels = sys.modules[f"{PKG.name}.labels"] if f"{PKG.name}.labels" in sys.modules else None

    def by_key(self):
        return {d.key: d for d in self.sensor.SENSOR_DESCRIPTIONS}

    def test_label_sensors_are_enums_with_lowercase_state(self):
        by = self.by_key()
        for key in ("stress_qualifier", "hrv_status", "last_activity_type", "sleep_score_stress"):
            self.assertEqual(by[key].device_class.value, "enum", key)
            self.assertIsNone(by[key].state_class, key)
            self.assertTrue(by[key].options, key)
        data = {"daily": DATA["daily"], "sleep": DATA["sleep"], "activities": DATA["activities"]}
        self.assertEqual(by["stress_qualifier"].value_fn(data["daily"]), "balanced")
        self.assertEqual(by["hrv_status"].value_fn(data["sleep"]), "balanced")
        self.assertEqual(by["last_activity_type"].value_fn(data["activities"]), "running")

    def test_every_word_list_has_both_languages(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("labels_check", PKG / "labels.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name, entries in mod.LABELS.items():
            for key, (en, de) in entries.items():
                self.assertEqual(key, key.lower(), (name, key))
                self.assertTrue(en and de, (name, key))
        for d in self.sensor.SENSOR_DESCRIPTIONS:
            if d.labels:
                self.assertIn(d.labels, mod.LABELS)
                self.assertEqual(list(d.options), sorted(mod.LABELS[d.labels]))

    def test_unlisted_value_is_kept_in_options(self):
        by = self.by_key()
        desc = by["last_activity_type"]
        coordinator = type("C", (), {"data": {"activities": [{"activityId": 2, "activityType": {"typeKey": "Curling"}}]}})()
        entity = self.sensor.GarminSensor.__new__(self.sensor.GarminSensor)
        entity.entity_description = desc
        entity.coordinator = coordinator
        self.assertEqual(entity.native_value, "curling")
        self.assertIn("curling", entity.options)
        self.assertIn("running", entity.options)


if __name__ == "__main__":
    unittest.main()
