"""Build the sensor list against stubbed Home Assistant modules and run every value function."""

import enum
import importlib.util
import sys
import types
import unittest
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


def install_stubs():
    dc = make_enum("SensorDeviceClass", "DISTANCE", "DURATION", "TIMESTAMP", "VOLUME", "WEIGHT")
    sc = make_enum("SensorStateClass", "MEASUREMENT", "TOTAL", "TOTAL_INCREASING")
    stub("homeassistant")
    stub("homeassistant.components")
    stub("homeassistant.components.sensor", SensorDeviceClass=dc, SensorStateClass=sc,
         SensorEntity=distinct('SensorEntity'), SensorEntityDescription=SensorEntityDescription)
    stub("homeassistant.const", PERCENTAGE="%",
         EntityCategory=make_enum("EntityCategory", "DIAGNOSTIC", "CONFIG"),
         UnitOfLength=make_enum("UnitOfLength", "METERS"), UnitOfMass=make_enum("UnitOfMass", "KILOGRAMS"),
         UnitOfTime=make_enum("UnitOfTime", "MINUTES", "SECONDS"),
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

    def test_prunes_only_empty_fields_of_answered_endpoints(self):
        data = {k: dict(v) for k, v in DATA.items()}
        data["sleep"] = {"sleep": None, "hrv_summaries": []}  # sleep not available yet
        pruned = self.sensor.sensors_to_prune(data)
        # weight answered: BMI is empty -> pruned; body fat has a value -> kept
        self.assertIn("bmi", pruned)
        self.assertNotIn("body_fat", pruned)
        self.assertNotIn("weight", pruned)
        # summary answered but has no active calories -> pruned
        self.assertIn("active_calories", pruned)
        self.assertNotIn("consumed_calories", pruned)  # already disabled by default
        self.assertNotIn("steps", pruned)
        # sleep endpoint returned nothing: nothing of it is pruned
        self.assertFalse({k for k in pruned if k.startswith("sleep_") or k.startswith("hrv_")})

    def test_nothing_pruned_without_data(self):
        self.assertEqual(self.sensor.sensors_to_prune({}), set())
        self.assertEqual(self.sensor.sensors_to_prune({"daily": {}}), set())

    def test_hidden_by_default_and_diagnostics_untouched(self):
        pruned = self.sensor.sensors_to_prune(DATA)
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


if __name__ == "__main__":
    unittest.main()
