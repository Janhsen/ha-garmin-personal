"""Sensors for the Garmin Personal API integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfMass,
    UnitOfSpeed,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import OPT_INTRADAY
from .coordinator import GarminConfigEntry, GarminCoordinator
from .entity import device_info
from .history import HISTORY_KEYS, manager_for
from .labels import LABELS
from .repairs import key_expires_at
from .values import (
    ValueFn,
    activity_number,
    activity_text,
    activity_timestamp,
    default_hr_zones,
    dig,
    finish_number,
    first_item,
    fitness_age_at,
    fitness_age_item,
    from_garmin,
    hr_zone_at,
    item_number,
    latest_hrv,
    latest_weight,
    number_at,
    parse_timestamp,
    series_pairs,
    text_at,
    timestamp_at,
    to_number,
    weight_at,
)

PARALLEL_UPDATES = 0

BPM = "bpm"
KCAL = "kcal"
STEPS = "steps"
MINUTES = UnitOfTime.MINUTES
SECONDS = UnitOfTime.SECONDS
YEARS = UnitOfTime.YEARS

ATTRIBUTE_TEXT_LIMIT = 255
AttrsFn = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]


@dataclass(frozen=True, kw_only=True)
class GarminSensorDescription(SensorEntityDescription):
    """Describes one sensor: which coordinator group and how to read its value."""

    group: str
    value_fn: ValueFn
    attrs_fn: AttrsFn | None = None
    intraday: bool = False
    labels: str | None = None


def _d(
    key: str,
    group: str,
    value_fn: ValueFn,
    *,
    unit: str | None = None,
    device_class: SensorDeviceClass | None = None,
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT,
    enabled: bool = True,
    category: EntityCategory | None = None,
    attrs: AttrsFn | None = None,
    intraday: bool = False,
    precision: int | None = None,
    labels: str | None = None,
    open_enum: bool = False,
    suggested_unit: str | None = None,
) -> GarminSensorDescription:
    if unit == MINUTES and device_class is None:
        device_class = DURATION
    if group == "sleep" and _is_night_value(key):
        # A night with a duration of 0 or less was not measured: no value, so the last night is held.
        value_fn = _measured_night(value_fn)
        if attrs is not None:
            attrs = _measured_night(attrs)
    options = None
    if labels is not None or open_enum:
        # A word list: shown translated, state is the lower-case Garmin key. ``open_enum`` has no list
        # yet (Garmin's values are not known): every value seen is added to the options and logged once.
        device_class = SensorDeviceClass.ENUM
        state_class = None
        options = sorted(LABELS[labels]) if labels is not None else []
        value_fn = _enum_value(value_fn)
    return GarminSensorDescription(
        key=key,
        translation_key=key,
        group=group,
        value_fn=value_fn,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=state_class,
        entity_registry_enabled_default=enabled,
        entity_category=category,
        attrs_fn=attrs,
        intraday=intraday,
        suggested_display_precision=precision,
        suggested_unit_of_measurement=suggested_unit,
        labels=labels,
        options=options,
    )


def _enum_value(inner: ValueFn) -> ValueFn:
    def value(data: Mapping[str, Any]) -> str | None:
        raw = inner(data)
        text = None if raw is None else str(raw).lower()
        # "unknown" is Home Assistant's own state for "no value": a Garmin "UNKNOWN" is the same thing.
        return None if text in (None, "unknown", "unavailable") else text

    return value


def _is_night_value(key: str) -> bool:
    """Sleep sensors that read the night record (not HRV, not naps, which can exist without a night)."""
    return key.startswith("sleep_")


def _measured_night(inner: Callable[[Mapping[str, Any]], Any]) -> Callable[[Mapping[str, Any]], Any]:
    def value(data: Mapping[str, Any]) -> Any:
        duration = to_number(dig(data, "sleep", "sleepTimeSeconds"))
        return None if duration is not None and duration <= 0 else inner(data)

    return value


_LOGGER = logging.getLogger(__name__)
_SEEN_UNLISTED: set[tuple[str, str]] = set()
# Nightly and body values are published once and then vanish from Garmin's answer; keep the last one.
KEEP_LAST_GROUPS = frozenset({"sleep", "body"})

TOTAL = SensorStateClass.TOTAL_INCREASING
DURATION = SensorDeviceClass.DURATION
TIMESTAMP = SensorDeviceClass.TIMESTAMP
NO_CLASS = None


def _summary(*path: str, **kwargs: Any) -> ValueFn:
    inner = number_at("summary", *path, **kwargs)

    def value(data: Mapping[str, Any]) -> float | int | None:
        # A day from another source (e.g. imported "fitbit" data) is never shown as a Garmin value.
        return inner(data) if from_garmin(data.get("summary")) else None

    return value


def _body_battery_level(data: Mapping[str, Any]) -> str | None:
    return text_at("summary", "bodyBatteryDynamicFeedbackEvent", "bodyBatteryLevel")(data) \
        if from_garmin(data.get("summary")) else None


def _stress_qualifier(data: Mapping[str, Any]) -> str | None:
    return text_at("summary", "stressQualifier")(data) if from_garmin(data.get("summary")) else None


def _sleep_score(name: str) -> ValueFn:
    return number_at("sleep", "sleepScores", name, "value")


def _sleep_score_label(name: str) -> ValueFn:
    """Some score parts carry only a rating (``qualifierKey``) and no number."""
    return text_at("sleep", "sleepScores", name, "qualifierKey")


def _sleep_score_attrs(name: str) -> AttrsFn:
    def attrs(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
        item = dig(data, "sleep", "sleepScores", name)
        if not isinstance(item, Mapping):
            return None
        return {k: item.get(k) for k in ("qualifierKey", "optimalStart", "optimalEnd") if k in item}

    return attrs


def _sleep_alignment_attrs(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Garmin's own numbers (minutes after midnight, as delivered), no conversion."""
    out: dict[str, Any] = {}
    for name, path in (
        ("optimal_window_start_min", ("sleep", "sleepAlignment", "optimalSleepWindowStartMins")),
        ("optimal_window_end_min", ("sleep", "sleepAlignment", "optimalSleepWindowEndMins")),
        ("optimal_window_midpoint_min", ("sleep", "sleepAlignment", "optimalSleepWindowMidpointMins")),
        ("last_sleep_midpoint_min", ("sleep", "sleepAlignment", "lastSleepMidpointMins")),
        ("recommended_bedtime_start_min", ("sleep", "sleepNeed", "recommendedBedtimeStartMins")),
        ("recommended_bedtime_end_min", ("sleep", "sleepNeed", "recommendedBedtimeEndMins")),
    ):
        value = dig(data, *path)
        if value is not None:
            out[name] = value
    return out or None


def _body_battery_events(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    summary = data.get("summary")
    if not isinstance(summary, Mapping) or not from_garmin(summary):
        return None
    out: dict[str, Any] = {}
    for name, key in (("feedback", "bodyBatteryDynamicFeedbackEvent"),
                      ("end_of_day_feedback", "endOfDayBodyBatteryDynamicFeedbackEvent")):
        event = summary.get(key)
        if isinstance(event, Mapping):
            out[name] = {k: event.get(k) for k in ("eventTimestampGmt", "bodyBatteryLevel", "feedbackShortType")}
    events = summary.get("bodyBatteryActivityEventList")
    if isinstance(events, list):
        out["events"] = [
            {k: e.get(k) for k in ("eventType", "eventStartTimeGmt", "durationInMilliseconds",
                                    "bodyBatteryImpact", "shortFeedback")}
            for e in events if isinstance(e, Mapping)
        ]
    return out or None


def _hrv_attrs(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    item = latest_hrv(data)
    baseline = item.get("baseline") if item else None
    if not isinstance(baseline, Mapping):
        return None
    return {
        "baseline_low_upper": baseline.get("lowUpper"),
        "baseline_balanced_low": baseline.get("balancedLow"),
        "baseline_balanced_upper": baseline.get("balancedUpper"),
        "baseline_marker": baseline.get("markerValue"),
        "calendar_date": item.get("calendarDate"),
    }


def _hrv(key: str) -> ValueFn:
    """A number from the newest HRV day that has a night average (same day as the attributes)."""

    def value(data: Mapping[str, Any]) -> float | int | None:
        item = latest_hrv(data)
        number = to_number(item.get(key)) if item else None
        return None if number is None else finish_number(number)

    return value


def _hrv_text(key: str) -> ValueFn:
    def value(data: Mapping[str, Any]) -> str | None:
        item = latest_hrv(data)
        raw = item.get(key) if item else None
        return None if raw is None else str(raw)[:255]

    return value


def _hr_intraday(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return {"values": series_pairs(dig(data, "heart_rate", "heartRateValues"))}


def _body_battery_intraday(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The body battery series; the column of the level is looked up in Garmin's descriptor list."""
    report = first_item(data, "body_battery")
    descriptors = dig(report, "bodyBatteryValueDescriptorDTOList")
    index: int | None = None
    for descriptor in descriptors if isinstance(descriptors, list) else []:
        if isinstance(descriptor, Mapping) and descriptor.get("bodyBatteryValueDescriptorKey") == "bodyBatteryLevel":
            raw = descriptor.get("bodyBatteryValueDescriptorIndex", descriptor.get("index"))
            number = to_number(raw)
            index = int(number) if number is not None and number >= 0 else None
            break
    if index is None:
        return {"values": []}  # column unknown: no series rather than a guessed column
    # chunks=288 repeats some timestamps (same value) and ends in null placeholders (dropped by series_pairs)
    unique: dict[float, list[float]] = {}
    for pair in series_pairs(dig(report, "bodyBatteryValuesArray"), index):
        unique.setdefault(pair[0], pair)
    return {"values": list(unique.values())}


def _spo2_intraday(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return {"hourly_values": series_pairs(dig(data, "spo2", "spO2HourlyAverages"))}


def _activity_attrs(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    activity = first_item(data, "activities")
    if not activity:
        return None
    keys = (
        "activityId",
        "description",
        "locationName",
        "startLatitude",
        "startLongitude",
        "elevationGain",
        "elevationLoss",
        "averageSpeed",
        "maxSpeed",
        "avgPower",
        "maxPower",
        "normPower",
        "steps",
        "lapCount",
        "manufacturer",
        "isFavorite",
        "isPR",
        "hasPolyline",
        "trainingEffectLabel",
        "aerobicTrainingEffectMessage",
        "anaerobicTrainingEffectMessage",
        "moderateIntensityMinutes",
        "vigorousIntensityMinutes",
        "differenceBodyBattery",
        "avgStress",
        "avgRespirationRate",
        "hrTimeInZone_1",
        "hrTimeInZone_2",
        "hrTimeInZone_3",
        "hrTimeInZone_4",
        "hrTimeInZone_5",
        "fastestSplit_1000",
        "fastestSplit_1609",
        "fastestSplit_5000",
        "fastestSplit_10000",
        "fastestSplit_21098",
        "fastestSplit_42195",
    )
    attrs: dict[str, Any] = {k: activity[k] for k in keys if k in activity}
    if isinstance(attrs.get("description"), str):
        attrs["description"] = attrs["description"][:ATTRIBUTE_TEXT_LIMIT]
    attrs["activity_type"] = dig(activity, "activityType", "typeKey")
    attrs["event_type"] = dig(activity, "eventType", "typeKey")
    return attrs


def _account_attrs(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    profile = data.get("profile")
    if not isinstance(profile, Mapping):
        return None
    keys = (
        "preferredLocale",
        "measurementSystem",
        "firstDayOfWeek",
        "timeZone",
        "hydrationMeasurementUnit",
        "glucoseMeasurementUnit",
        "wheelchairModeEnabled",
        "availableTrainingDays",
        "preferredLongTrainingDays",
    )
    return {k: profile.get(k) for k in keys if k in profile}


def _hr_zone_attrs(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    zones = default_hr_zones(data)
    if not zones:
        return None
    return {
        "sport": zones.get("sport"),
        "training_method": zones.get("trainingMethod"),
        **{f"zone_{n}_floor": zones.get(f"zone{n}Floor") for n in range(1, 6)},
    }


def _weight_attrs(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    entry = latest_weight(data)
    if not entry:
        return None
    return {
        "source_type": entry.get("sourceType"),
        "calendar_date": entry.get("calendarDate"),
        "weight_delta_g": entry.get("weightDelta"),
    }


def _fitness_age_attrs(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    fitness = fitness_age_item(data)
    if fitness is None:
        return None
    attrs: dict[str, Any] = {
        "invalid_reason": fitness.get("invalidReason"),
        "last_updated": fitness.get("lastUpdated"),
    }
    if fitness.get("previousFitnessAge") is not None:
        attrs["previous_fitness_age"] = fitness["previousFitnessAge"]  # Garmin's own earlier value
    components = fitness.get("components")
    if isinstance(components, Mapping):
        attrs["components"] = dict(components)
    return attrs


def _heart_rate_alert_attrs(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Garmin's alert thresholds, when the heart rate answer of the day was requested."""
    out: dict[str, Any] = {}
    for name, key in (("high_threshold", "abnormalHrThresholdValue"), ("low_threshold", "lowAbnormalHrThresholdValue")):
        value = to_number(dig(data, "heart_rate", key))
        if value is not None:
            out[name] = value
    return out or None


SENSORS: tuple[GarminSensorDescription, ...] = (
    # ---- Daily activity tracker (group "daily") -------------------------------------
    _d("steps", "daily", _summary("totalSteps"), unit=STEPS, state_class=TOTAL),
    _d("step_goal", "daily", _summary("dailyStepGoal"), unit=STEPS, category=EntityCategory.DIAGNOSTIC),
    _d("distance", "daily", _summary("totalDistanceMeters"), unit=UnitOfLength.METERS,
       device_class=SensorDeviceClass.DISTANCE, state_class=TOTAL, precision=0),
    _d("total_calories", "daily", _summary("totalKilocalories"), unit=KCAL, state_class=TOTAL),
    _d("active_calories", "daily", _summary("activeKilocalories"), unit=KCAL, state_class=TOTAL),
    _d("resting_calories", "daily", _summary("bmrKilocalories"), unit=KCAL, state_class=TOTAL),
    _d("consumed_calories", "daily", _summary("consumedKilocalories"), unit=KCAL, state_class=TOTAL, enabled=False),
    _d("remaining_calories", "daily", _summary("remainingKilocalories", allow_negative=True), unit=KCAL, enabled=False),
    _d("moderate_intensity_minutes", "daily", _summary("moderateIntensityMinutes"), unit=MINUTES,
       state_class=TOTAL),
    _d("vigorous_intensity_minutes", "daily", _summary("vigorousIntensityMinutes"), unit=MINUTES,
       state_class=TOTAL),
    _d("intensity_minutes_goal", "daily", _summary("intensityMinutesGoal"), unit=MINUTES,
       category=EntityCategory.DIAGNOSTIC, enabled=False),
    _d("floors_ascended", "daily", _summary("floorsAscended"), state_class=TOTAL, precision=0),
    _d("floors_descended", "daily", _summary("floorsDescended"), state_class=TOTAL, precision=0),
    _d("floors_goal", "daily", _summary("userFloorsAscendedGoal"), category=EntityCategory.DIAGNOSTIC, enabled=False),
    _d("highly_active_time", "daily", _summary("highlyActiveSeconds"), unit=SECONDS, device_class=DURATION,
       state_class=TOTAL, enabled=False),
    _d("active_time", "daily", _summary("activeSeconds"), unit=SECONDS, device_class=DURATION,
       state_class=TOTAL, enabled=False),
    _d("sedentary_time", "daily", _summary("sedentarySeconds"), unit=SECONDS, device_class=DURATION,
       state_class=TOTAL, enabled=False),
    _d("heart_rate_resting", "daily", _summary("restingHeartRate", zero_is_none=True), unit=BPM),
    _d("heart_rate_resting_7d", "daily", _summary("lastSevenDaysAvgRestingHeartRate", zero_is_none=True), unit=BPM),
    _d("heart_rate_min", "daily", _summary("minHeartRate", zero_is_none=True), unit=BPM),
    _d("heart_rate_max", "daily", _summary("maxHeartRate", zero_is_none=True), unit=BPM,
       attrs=_hr_intraday, intraday=True),
    _d("heart_rate_alerts", "daily", _summary("abnormalHeartRateAlertsCount"), state_class=TOTAL, precision=0,
       attrs=_heart_rate_alert_attrs, enabled=False),
    _d("stress_average", "daily", _summary("averageStressLevel")),
    _d("stress_max", "daily", _summary("maxStressLevel"), enabled=False),
    _d("stress_qualifier", "daily", _stress_qualifier, labels="stress"),
    _d("stress_rest_time", "daily", _summary("restStressDuration"), unit=SECONDS, device_class=DURATION, state_class=TOTAL,
       enabled=False),
    _d("stress_low_time", "daily", _summary("lowStressDuration"), unit=SECONDS, device_class=DURATION, state_class=TOTAL,
       enabled=False),
    _d("stress_medium_time", "daily", _summary("mediumStressDuration"), unit=SECONDS, device_class=DURATION, state_class=TOTAL,
       enabled=False),
    _d("stress_high_time", "daily", _summary("highStressDuration"), unit=SECONDS, device_class=DURATION, state_class=TOTAL,
       enabled=False),
    _d("body_battery", "daily", _summary("bodyBatteryMostRecentValue"), unit=PERCENTAGE,
       attrs=_body_battery_intraday, intraday=True),
    _d("body_battery_level", "daily", _body_battery_level, labels="body_battery_level", state_class=NO_CLASS,
       attrs=_body_battery_events, enabled=False),
    _d("body_battery_high", "daily", _summary("bodyBatteryHighestValue"), unit=PERCENTAGE),
    _d("body_battery_low", "daily", _summary("bodyBatteryLowestValue"), unit=PERCENTAGE),
    _d("body_battery_charged", "daily", _summary("bodyBatteryChargedValue"), unit=PERCENTAGE, state_class=TOTAL,
       enabled=False),
    _d("body_battery_drained", "daily", _summary("bodyBatteryDrainedValue"), unit=PERCENTAGE, state_class=TOTAL,
       enabled=False),
    _d("body_battery_at_wake", "daily", _summary("bodyBatteryAtWakeTime"), unit=PERCENTAGE, enabled=False),
    _d("body_battery_during_sleep", "daily", _summary("bodyBatteryDuringSleep"), unit=PERCENTAGE, enabled=False),
    _d("spo2_average", "daily", number_at("spo2", "averageSpO2", zero_is_none=True), unit=PERCENTAGE,
       attrs=_spo2_intraday, intraday=True),
    _d("spo2_lowest", "daily", number_at("spo2", "lowestSpO2", zero_is_none=True), unit=PERCENTAGE),
    _d("spo2_latest", "daily", number_at("spo2", "latestSpO2", zero_is_none=True), unit=PERCENTAGE),
    _d("spo2_7d", "daily", number_at("spo2", "lastSevenDaysAvgSpO2"), unit=PERCENTAGE, enabled=False),
    _d("stress_percentage", "daily", _summary("stressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("stress_rest_percentage", "daily", _summary("restStressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("stress_activity_percentage", "daily", _summary("activityStressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("stress_low_percentage", "daily", _summary("lowStressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("stress_medium_percentage", "daily", _summary("mediumStressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("stress_high_percentage", "daily", _summary("highStressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("altitude_average", "daily", _summary("averageMonitoringEnvironmentAltitude", allow_negative=True), unit="m",
       device_class=SensorDeviceClass.DISTANCE, enabled=False),
    _d("respiration_highest", "daily", _summary("highestRespirationValue", zero_is_none=True), unit="brpm", enabled=False),
    _d("respiration_lowest", "daily", _summary("lowestRespirationValue", zero_is_none=True), unit="brpm", enabled=False),
    _d("heart_rate_avg_min", "daily", _summary("minAvgHeartRate", zero_is_none=True), unit=BPM, enabled=False),
    _d("heart_rate_avg_max", "daily", _summary("maxAvgHeartRate", zero_is_none=True), unit=BPM, enabled=False),
    _d("respiration_waking", "daily", _summary("avgWakingRespirationValue", zero_is_none=True), unit="brpm", enabled=False),
    _d("respiration_latest", "daily", _summary("latestRespirationValue", zero_is_none=True), unit="brpm", enabled=False),
    _d("hydration", "daily", item_number("hydration", "valueInML"), unit=UnitOfVolume.MILLILITERS,
       device_class=SensorDeviceClass.VOLUME, state_class=TOTAL),
    _d("hydration_goal", "daily", item_number("hydration", "goalInML"), unit=UnitOfVolume.MILLILITERS,
       device_class=SensorDeviceClass.VOLUME, state_class=NO_CLASS, category=EntityCategory.DIAGNOSTIC, enabled=False),
    _d("hydration_sweat_loss", "daily", item_number("hydration", "sweatLossInML"), unit=UnitOfVolume.MILLILITERS,
       device_class=SensorDeviceClass.VOLUME, state_class=NO_CLASS, enabled=False),
    _d("last_sync", "daily", timestamp_at("summary", "lastSyncTimestampGMT"), device_class=TIMESTAMP,
       state_class=NO_CLASS, category=EntityCategory.DIAGNOSTIC),
    # ---- Sleep and HRV (group "sleep") ------------------------------------------------
    _d("sleep_duration", "sleep", number_at("sleep", "sleepTimeSeconds"), unit=SECONDS, device_class=DURATION,
       state_class=NO_CLASS),
    _d("sleep_deep", "sleep", number_at("sleep", "deepSleepSeconds"), unit=SECONDS, device_class=DURATION,
       state_class=NO_CLASS),
    _d("sleep_light", "sleep", number_at("sleep", "lightSleepSeconds"), unit=SECONDS, device_class=DURATION,
       state_class=NO_CLASS),
    _d("sleep_rem", "sleep", number_at("sleep", "remSleepSeconds"), unit=SECONDS, device_class=DURATION,
       state_class=NO_CLASS),
    _d("sleep_awake", "sleep", number_at("sleep", "awakeSleepSeconds"), unit=SECONDS, device_class=DURATION,
       state_class=NO_CLASS),
    _d("nap_duration", "sleep", number_at("sleep", "napTimeSeconds"), unit=SECONDS, device_class=DURATION,
       state_class=NO_CLASS, enabled=False),
    _d("sleep_score", "sleep", _sleep_score("overall"), attrs=_sleep_score_attrs("overall")),
    _d("sleep_score_duration", "sleep", _sleep_score_label("totalDuration"), labels="rating", attrs=_sleep_score_attrs("totalDuration"), enabled=False),
    _d("sleep_score_stress", "sleep", _sleep_score_label("stress"), labels="rating", attrs=_sleep_score_attrs("stress"), enabled=False),
    _d("sleep_score_restlessness", "sleep", _sleep_score_label("restlessness"), labels="rating", attrs=_sleep_score_attrs("restlessness"), enabled=False),
    _d("sleep_score_awake_count", "sleep", _sleep_score_label("awakeCount"), labels="rating", attrs=_sleep_score_attrs("awakeCount"), enabled=False),
    _d("sleep_score_rem", "sleep", _sleep_score("remPercentage"), unit=PERCENTAGE, attrs=_sleep_score_attrs("remPercentage"), enabled=False),
    _d("sleep_score_light", "sleep", _sleep_score("lightPercentage"), unit=PERCENTAGE, attrs=_sleep_score_attrs("lightPercentage"), enabled=False),
    _d("sleep_score_deep", "sleep", _sleep_score("deepPercentage"), unit=PERCENTAGE, attrs=_sleep_score_attrs("deepPercentage"), enabled=False),
    _d("sleep_start", "sleep", timestamp_at("sleep", "sleepStartTimestampGMT"), device_class=TIMESTAMP,
       state_class=NO_CLASS),
    _d("sleep_end", "sleep", timestamp_at("sleep", "sleepEndTimestampGMT"), device_class=TIMESTAMP,
       state_class=NO_CLASS),
    _d("sleep_awake_count", "sleep", number_at("sleep", "awakeCount"), enabled=False),
    _d("sleep_heart_rate", "sleep", number_at("sleep", "avgHeartRate", digits=0, zero_is_none=True), unit=BPM, enabled=False),
    _d("sleep_stress", "sleep", number_at("sleep", "avgSleepStress", digits=1), enabled=False),
    _d("sleep_spo2_average", "sleep", number_at("sleep", "averageSpO2Value", zero_is_none=True), unit=PERCENTAGE, enabled=False),
    _d("sleep_spo2_lowest", "sleep", number_at("sleep", "lowestSpO2Value", zero_is_none=True), unit=PERCENTAGE, enabled=False),
    _d("sleep_respiration_average", "sleep", number_at("sleep", "averageRespirationValue", zero_is_none=True), unit="brpm", enabled=False),
    _d("sleep_need", "sleep", number_at("sleep", "sleepNeed", "actual"), unit=MINUTES, state_class=NO_CLASS,
       enabled=False),
    _d("sleep_need_next", "sleep", number_at("sleep", "nextSleepNeed", "actual"), unit=MINUTES, state_class=NO_CLASS,
       enabled=False),
    _d("sleep_feedback", "sleep", text_at("sleep", "sleepScoreFeedback"), labels="sleep_feedback", state_class=NO_CLASS, enabled=False),
    _d("sleep_insight", "sleep", text_at("sleep", "sleepScoreInsight"), labels="sleep_insight", state_class=NO_CLASS, enabled=False),
    _d("sleep_personal_insight", "sleep", text_at("sleep", "sleepScorePersonalizedInsight"), labels="sleep_personal_insight",
       state_class=NO_CLASS, enabled=False),
    _d("sleep_alignment", "sleep", text_at("sleep", "sleepAlignment", "status"), labels="sleep_alignment",
       state_class=NO_CLASS, attrs=_sleep_alignment_attrs, enabled=False),
    _d("sleep_breathing_disruption", "sleep", text_at("sleep", "breathingDisruptionSeverity"), state_class=NO_CLASS,
       open_enum=True, enabled=False),
    _d("hrv_last_night", "sleep", _hrv("lastNightAvg"), unit="ms", attrs=_hrv_attrs),
    _d("hrv_weekly", "sleep", _hrv("weeklyAvg"), unit="ms"),
    _d("hrv_5min_high", "sleep", _hrv("lastNight5MinHigh"), unit="ms", enabled=False),
    _d("hrv_status", "sleep", _hrv_text("status"), labels="hrv_status"),
    _d("hrv_feedback", "sleep", _hrv_text("feedbackPhrase"), labels="hrv_feedback", state_class=NO_CLASS, enabled=False),
    # ---- Body (group "body") ----------------------------------------------------------
    _d("weight", "body", weight_at("weight", scale=1000, zero_is_none=True), unit=UnitOfMass.KILOGRAMS,
       device_class=SensorDeviceClass.WEIGHT, attrs=_weight_attrs, precision=2),
    _d("bmi", "body", weight_at("bmi", digits=1, zero_is_none=True)),
    _d("body_fat", "body", weight_at("bodyFat", digits=1, zero_is_none=True), unit=PERCENTAGE),
    _d("body_water", "body", weight_at("bodyWater", digits=1, zero_is_none=True), unit=PERCENTAGE),
    _d("muscle_mass", "body", weight_at("muscleMass", scale=1000, zero_is_none=True), unit=UnitOfMass.KILOGRAMS,
       device_class=SensorDeviceClass.WEIGHT, precision=2),
    _d("bone_mass", "body", weight_at("boneMass", scale=1000, zero_is_none=True), unit=UnitOfMass.KILOGRAMS,
       device_class=SensorDeviceClass.WEIGHT, precision=2),
    _d("visceral_fat", "body", weight_at("visceralFat"), enabled=False),
    _d("metabolic_age", "body", weight_at("metabolicAge", digits=0), unit=YEARS, enabled=False),
    _d("fitness_age", "body", fitness_age_at("fitnessAge", digits=1), unit=YEARS, attrs=_fitness_age_attrs),
    _d("fitness_age_achievable", "body", fitness_age_at("achievableFitnessAge", digits=1), unit=YEARS,
       enabled=False),
    _d("chronological_age", "body", fitness_age_at("chronologicalAge"), unit=YEARS, enabled=False,
       category=EntityCategory.DIAGNOSTIC),
    # ---- Activities (group "activities") ----------------------------------------------
    _d("last_activity", "activities", activity_text("activityName"), state_class=NO_CLASS, attrs=_activity_attrs),
    _d("last_activity_type", "activities", activity_text("activityType", "typeKey"), labels="activity_type"),
    _d("last_activity_start", "activities", activity_timestamp("startTimeGMT"), device_class=TIMESTAMP,
       state_class=NO_CLASS),
    _d("last_activity_distance", "activities", activity_number("distance"), unit=UnitOfLength.METERS,
       device_class=SensorDeviceClass.DISTANCE, state_class=NO_CLASS, precision=0),
    _d("last_activity_duration", "activities", activity_number("duration"), unit=SECONDS, device_class=DURATION,
       state_class=NO_CLASS),
    _d("last_activity_calories", "activities", activity_number("calories", digits=0), unit=KCAL, state_class=NO_CLASS),
    _d("last_activity_avg_hr", "activities", activity_number("averageHR", digits=0, zero_is_none=True), unit=BPM, state_class=NO_CLASS),
    _d("last_activity_max_hr", "activities", activity_number("maxHR", digits=0, zero_is_none=True), unit=BPM, state_class=NO_CLASS),
    _d("last_activity_aerobic_te", "activities", activity_number("aerobicTrainingEffect", digits=1),
       state_class=NO_CLASS, enabled=False),
    _d("last_activity_anaerobic_te", "activities", activity_number("anaerobicTrainingEffect", digits=1),
       state_class=NO_CLASS, enabled=False),
    _d("last_activity_load", "activities", activity_number("activityTrainingLoad", digits=0), state_class=NO_CLASS,
       enabled=False),
    _d("last_activity_vo2max", "activities", activity_number("vO2MaxValue", digits=1), unit="ml/kg/min",
       state_class=NO_CLASS, enabled=False),
    _d("last_activity_avg_speed", "activities", activity_number("averageSpeed", zero_is_none=True),
       unit=UnitOfSpeed.METERS_PER_SECOND, device_class=SensorDeviceClass.SPEED, state_class=NO_CLASS,
       suggested_unit=UnitOfSpeed.KILOMETERS_PER_HOUR, precision=1, enabled=False),
    _d("last_activity_max_speed", "activities", activity_number("maxSpeed", zero_is_none=True),
       unit=UnitOfSpeed.METERS_PER_SECOND, device_class=SensorDeviceClass.SPEED, state_class=NO_CLASS,
       suggested_unit=UnitOfSpeed.KILOMETERS_PER_HOUR, precision=1, enabled=False),
    _d("last_activity_elevation", "activities", activity_number("elevationGain", digits=0), unit=UnitOfLength.METERS,
       device_class=SensorDeviceClass.DISTANCE, state_class=NO_CLASS, enabled=False),
    _d("wellness_activities", "activities", lambda d: _count(d, "wellness_activities"), state_class=NO_CLASS,
       enabled=False),
    # ---- Profile (group "profile") ----------------------------------------------------
    _d("account", "profile", text_at("profile", "displayName"), state_class=NO_CLASS,
       category=EntityCategory.DIAGNOSTIC, attrs=_account_attrs),
    _d("hr_max_used", "profile", hr_zone_at("maxHeartRateUsed"), unit=BPM, category=EntityCategory.DIAGNOSTIC,
       attrs=_hr_zone_attrs),
    _d("hr_resting_used", "profile", hr_zone_at("restingHeartRateUsed"), unit=BPM,
       category=EntityCategory.DIAGNOSTIC, enabled=False),
    _d("hr_lactate_threshold", "profile", hr_zone_at("lactateThresholdHeartRateUsed"), unit=BPM,
       category=EntityCategory.DIAGNOSTIC, enabled=False),
)


def _count(data: Mapping[str, Any], key: str) -> int | None:
    items = data.get(key)
    return len(items) if isinstance(items, list) else None


SENSOR_DESCRIPTIONS = SENSORS


def source_key(key: str) -> str:
    """Which coordinator data key a sensor reads from (for the one-time pruning)."""
    if key.startswith("sleep_") or key == "nap_duration":
        return "sleep"
    if key.startswith("hrv_"):
        return "hrv_summaries"
    if key.startswith("spo2_"):
        return "spo2"
    if key.startswith("hydration"):
        return "hydration"
    if key in ("fitness_age", "fitness_age_achievable", "chronological_age"):
        return "fitness_age"
    if key in ("weight", "bmi", "body_fat", "body_water", "muscle_mass", "bone_mass",
               "visceral_fat", "metabolic_age"):
        return "weight"
    if key == "wellness_activities":
        return "wellness_activities"
    if key.startswith("last_activity"):
        return "activities"
    if key == "account":
        return "profile"
    if key.startswith("hr_"):
        return "hr_zones"
    return "summary"


def has_content(value: Any) -> bool:
    """True if Garmin actually answered: any non-empty value somewhere inside."""
    if value is None:
        return False
    if isinstance(value, Mapping):
        return any(has_content(v) for v in value.values())
    if isinstance(value, list):
        return any(has_content(v) for v in value)
    return True


# Sensors are only disabled when the answers are complete enough to trust: daily and sleep
# values can appear later in the day, so they are never disabled automatically. The activity
# sensors (``last_activity_*``) only describe the newest activity: a strength workout without
# heart rate or distance must not switch them off for good.
PRUNE_MIN_ENTRY_AGE = timedelta(hours=24)
PRUNE_SKIP_GROUPS = frozenset({"daily", "sleep", "activities"})


def prune_blocker(
    data_by_group: Mapping[str, Mapping[str, Any]], entry_created: datetime | None, now: datetime | None = None
) -> str | None:
    """Why empty sensors must not be disabled yet, or ``None`` if the decision may be taken now."""
    now = now or dt_util.now()
    if entry_created is None:
        return "the age of the account entry is unknown"
    if entry_created.tzinfo is None:
        entry_created = entry_created.replace(tzinfo=UTC)
    if now - entry_created < PRUNE_MIN_ENTRY_AGE:
        return "the account was added less than 24 hours ago"
    synced = parse_timestamp(dig(data_by_group.get("daily"), "summary", "lastSyncTimestampGMT"))
    if synced is None or synced.astimezone(now.tzinfo).date() != now.date():
        return "the watch has not synchronised today"
    return None


def sensors_to_prune(
    data_by_group: Mapping[str, Mapping[str, Any]],
    entry_created: datetime | None = None,
    now: datetime | None = None,
) -> set[str]:
    """Sensors that are empty although their endpoint answered (body and profile values only).

    Nothing is returned while the watch has not synchronised today or the account is less than
    24 hours old (``prune_blocker``); the caller must then not mark the pruning as done.
    Endpoints that returned nothing at all are left alone, since their sensors will fill in later.
    """
    reason = prune_blocker(data_by_group, entry_created, now)
    if reason is not None:
        _LOGGER.info("Not disabling empty sensors yet: %s", reason)
        return set()
    keys: set[str] = set()
    for description in SENSOR_DESCRIPTIONS:
        if (
            not description.entity_registry_enabled_default
            or description.entity_category
            or description.group in PRUNE_SKIP_GROUPS
        ):
            continue
        data = data_by_group.get(description.group)
        if not data:
            continue
        source = data.get(source_key(description.key))
        if source_key(description.key) == "weight":
            answered = latest_weight(data) is not None
        else:
            answered = has_content(source)
        if answered and description.value_fn(data) is None:
            keys.add(description.key)
    _LOGGER.info(
        "Disabling %d sensor(s) for which Garmin returned no value (they can be enabled again): %s",
        len(keys),
        ", ".join(sorted(keys)) or "-",
    )
    return keys


async def async_setup_entry(
    hass: HomeAssistant, entry: GarminConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the sensors of a config entry."""
    runtime = entry.runtime_data
    entities: list[SensorEntity] = [
        GarminSensor(runtime.coordinators[description.group], entry, description)
        for description in SENSOR_DESCRIPTIONS
        if description.group in runtime.coordinators
    ]
    entities.append(GarminKeyExpirySensor(entry))
    entities.extend(GarminHistorySensor(entry, key, unit) for key, unit in HISTORY_UNITS.items())
    async_add_entities(entities)


class GarminSensor(CoordinatorEntity[GarminCoordinator], RestoreSensor):
    """A sensor reading one value out of its coordinator's data.

    Sleep and body values keep their last known value (also across restarts) while Garmin
    returns nothing; ``held_value`` says so and ``last_seen`` is when this value first arrived
    here (not when it was measured). The state is derived without side effects; the held value
    is updated only when the coordinator delivers new data.
    """

    _attr_has_entity_name = True
    entity_description: GarminSensorDescription
    # Large series and personal detail that is useful live but should not be stored in the history.
    _unrecorded_attributes = frozenset(
        {
            "values", "hourly_values", "components", "events", "feedback", "end_of_day_feedback",
            "startLatitude", "startLongitude", "locationName", "description",
        }
    )

    def __init__(
        self,
        coordinator: GarminCoordinator,
        entry: GarminConfigEntry,
        description: GarminSensorDescription,
    ) -> None:
        """Set up the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry)
        self._keep = description.group in KEEP_LAST_GROUPS
        self._last_value: Any = None
        self._last_seen: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last known value after a restart."""
        await super().async_added_to_hass()
        if not self._keep:
            return
        stored = await self.async_get_last_sensor_data()
        if stored is not None and stored.native_value is not None:
            self._last_value = stored.native_value
        state = await self.async_get_last_state()
        # After a restart in the unavailable state the attributes are gone: last_seen stays unknown.
        if state is not None and getattr(state, "state", None) not in ("unavailable", "unknown"):
            self._last_seen = state.attributes.get("last_seen")
        self._remember()

    def _current(self) -> Any:
        """What Garmin delivers right now (``None`` if nothing)."""
        return self.entity_description.value_fn(self.coordinator.data) if self.coordinator.data else None

    def _remember(self) -> None:
        """Take over a new value as the one to hold (only called when data arrives)."""
        current = self._current()
        if current is None:
            return
        if current != self._last_value:
            self._last_seen = dt_util.utcnow().isoformat(timespec="seconds")
        self._last_value = current

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._keep:
            self._remember()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> StateType:
        """The current value, or the last known one for sleep and body values."""
        current = self._current()
        if current is not None or not self._keep:
            return current
        return self._last_value

    @property
    def options(self) -> list[str] | None:
        """Known keys plus the current one, so an unlisted Garmin value is shown instead of failing."""
        listed = self.entity_description.options
        if listed is None:
            return None
        current = self.native_value
        keys = list(listed)
        if isinstance(current, str) and current not in keys:
            keys.append(current)
            seen = (self.entity_description.key, current)
            if seen not in _SEEN_UNLISTED:
                _SEEN_UNLISTED.add(seen)
                _LOGGER.info("Garmin value %r for %s has no translation yet; please report it", current, seen[0])
        return keys

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Extra values; intraday series only if enabled in the options."""
        description = self.entity_description
        attrs: dict[str, Any] = {}
        if description.attrs_fn is not None and self.coordinator.data and not (
            description.intraday and not self._entry.options.get(OPT_INTRADAY, False)
        ):
            attrs.update(description.attrs_fn(self.coordinator.data) or {})
        if self._keep and self.native_value is not None:
            attrs["last_seen"] = self._last_seen
            attrs["held_value"] = self._current() is None
        return attrs or None


# translation key of the history sensor -> unit (see history.py)
HISTORY_UNITS: dict[str, str] = {"heart_rate_history": BPM, "body_battery_history": "%", "spo2_history": "%", "hrv_history": "ms"}


class GarminHistorySensor(RestoreSensor):
    """Carrier of a series' history: recorded states with the real measurement times.

    Disabled by default. The history itself is written by ``backfill_history`` and the automatic
    filling with their own timestamps. Its own state is the value of the newest point that the
    forward path (the live filling after a sync) handed over, with ``measured_at`` as its time;
    the initial load and manual runs for old days never touch it. It is restored after a restart.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = False
    _attr_available = True

    def __init__(self, entry: GarminConfigEntry, key: str, unit: str) -> None:
        """Set up the sensor."""
        self._entry = entry
        self._series = next((s for s, k in HISTORY_KEYS.items() if k == key), key)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info = device_info(entry)
        self._value: float | None = None
        self._measured_ms: int | None = None

    @property
    def native_value(self) -> float | None:
        """The value of the newest measuring point handed over by the live filling (a real Garmin value)."""
        return self._value

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Time of that measurement (ISO, with zone) and how far back the automatic load has come (a date)."""
        attrs: dict[str, str] = {}
        if self._measured_ms is not None:
            attrs["measured_at"] = dt_util.utc_from_timestamp(self._measured_ms / 1000).isoformat()
        runtime = getattr(self._entry, "runtime_data", None)
        manager = getattr(runtime, "history", None)
        if manager is not None:
            attrs.update(manager.progress.get(self._series) or {})
        return attrs or None

    def show_latest(self, ts_ms: int, value: float) -> None:
        """Take a newer measurement as the state; an older or equal one changes nothing (no new row)."""
        if self._measured_ms is not None and ts_ms <= self._measured_ms:
            return
        self._value, self._measured_ms = value, ts_ms
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the last value and its time, and let the history load report to this sensor."""
        await super().async_added_to_hass()
        stored = await self.async_get_last_sensor_data()
        state = await self.async_get_last_state()
        measured = getattr(state, "attributes", {}).get("measured_at") if state is not None else None
        parsed = dt_util.parse_datetime(measured) if isinstance(measured, str) else None
        value = getattr(stored, "native_value", None)
        if parsed is not None and isinstance(value, int | float) and not isinstance(value, bool):
            self._value, self._measured_ms = float(value), round(parsed.timestamp() * 1000)
        manager = manager_for(self.hass, self._entry)
        manager.listeners[self._series] = self.async_write_ha_state
        manager.latest_listeners[self._series] = self.show_latest
        if self._series in manager.latest:  # the live job ran before this sensor was added
            self.show_latest(*manager.latest[self._series])

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        manager = getattr(getattr(self._entry, "runtime_data", None), "history", None)
        if manager is not None:
            manager.listeners.pop(self._series, None)
            manager.latest_listeners.pop(self._series, None)


class GarminKeyExpirySensor(SensorEntity):
    """When the Personal API key runs out (from the validity chosen at setup).

    The value comes from the config entry alone, so it stays available when Garmin does not answer
    (for example because the key has already expired).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "key_expires"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: GarminConfigEntry) -> None:
        """Set up the sensor."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_key_expires"
        self._attr_device_info = device_info(entry)

    @property
    def available(self) -> bool:
        """Always available: the expiry is stored locally."""
        return True

    @property
    def native_value(self) -> Any:
        """Expiry time of the API key."""
        return key_expires_at(self._entry)
