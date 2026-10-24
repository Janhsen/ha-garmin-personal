"""Sensors for the Garmin Personal API integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from dataclasses import dataclass
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
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import OPT_INTRADAY
from .coordinator import GarminConfigEntry, GarminCoordinator
from .entity import device_info
from .labels import LABELS
from .repairs import key_expires_at
from .values import (
    ValueFn,
    activity_number,
    activity_text,
    activity_timestamp,
    default_hr_zones,
    dig,
    first_item,
    from_garmin,
    hr_zone_at,
    item_number,
    last_item,
    latest_weight,
    number_at,
    series_pairs,
    text_at,
    timestamp_at,
    weight_at,
)

PARALLEL_UPDATES = 0

BPM = "bpm"
KCAL = "kcal"
STEPS = "steps"
MINUTES = UnitOfTime.MINUTES
SECONDS = UnitOfTime.SECONDS

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
    icon: str | None = None,
    precision: int | None = None,
    labels: str | None = None,
) -> GarminSensorDescription:
    if unit == MINUTES and device_class is None:
        device_class = DURATION
    options = None
    if labels is not None:
        # A fixed word list: shown translated, state is the lower-case Garmin key.
        device_class = SensorDeviceClass.ENUM
        state_class = None
        options = sorted(LABELS[labels])
        inner = value_fn

        def value_fn(data: Mapping[str, Any], inner: ValueFn = inner) -> str | None:  # noqa: F811
            raw = inner(data)
            return None if raw is None else str(raw).lower()
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
        icon=icon,
        suggested_display_precision=precision,
        labels=labels,
        options=options,
    )


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
    item = last_item(data, "hrv_summaries")
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
    return item_number("hrv_summaries", key)


def _hrv_text(key: str) -> ValueFn:
    def value(data: Mapping[str, Any]) -> str | None:
        item = last_item(data, "hrv_summaries")
        raw = item.get(key) if item else None
        return None if raw is None else str(raw)[:255]

    return value


def _hr_intraday(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return {"values": series_pairs(dig(data, "heart_rate", "heartRateValues"))}


def _body_battery_intraday(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    report = first_item(data, "body_battery")
    descriptors = dig(report, "bodyBatteryValueDescriptorDTOList") or []
    index = 1
    for descriptor in descriptors if isinstance(descriptors, list) else []:
        if isinstance(descriptor, Mapping) and descriptor.get("bodyBatteryValueDescriptorKey") == "bodyBatteryLevel":
            index = descriptor.get("bodyBatteryValueDescriptorIndex", descriptor.get("index", 1))
    return {"values": series_pairs(dig(report, "bodyBatteryValuesArray"), int(index))}


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
    )
    attrs: dict[str, Any] = {k: activity[k] for k in keys if k in activity}
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
    fitness = data.get("fitness_age")
    if not isinstance(fitness, Mapping):
        return None
    attrs: dict[str, Any] = {
        "invalid_reason": fitness.get("invalidReason"),
        "last_updated": fitness.get("lastUpdated"),
    }
    components = fitness.get("components")
    if isinstance(components, Mapping):
        attrs["components"] = dict(components)
    return attrs


SENSORS: tuple[GarminSensorDescription, ...] = (
    # ---- Daily activity tracker (group "daily") -------------------------------------
    _d("steps", "daily", _summary("totalSteps"), unit=STEPS, state_class=TOTAL, icon="mdi:shoe-print"),
    _d("step_goal", "daily", _summary("dailyStepGoal"), unit=STEPS, category=EntityCategory.DIAGNOSTIC),
    _d("distance", "daily", _summary("totalDistanceMeters"), unit=UnitOfLength.METERS,
       device_class=SensorDeviceClass.DISTANCE, state_class=TOTAL, precision=0),
    _d("total_calories", "daily", _summary("totalKilocalories"), unit=KCAL, state_class=TOTAL, icon="mdi:fire"),
    _d("active_calories", "daily", _summary("activeKilocalories"), unit=KCAL, state_class=TOTAL, icon="mdi:fire"),
    _d("resting_calories", "daily", _summary("bmrKilocalories"), unit=KCAL, state_class=TOTAL, icon="mdi:fire"),
    _d("consumed_calories", "daily", _summary("consumedKilocalories"), unit=KCAL, state_class=TOTAL, enabled=False),
    _d("remaining_calories", "daily", _summary("remainingKilocalories"), unit=KCAL, enabled=False),
    _d("moderate_intensity_minutes", "daily", _summary("moderateIntensityMinutes"), unit=MINUTES,
       state_class=TOTAL, icon="mdi:run-fast"),
    _d("vigorous_intensity_minutes", "daily", _summary("vigorousIntensityMinutes"), unit=MINUTES,
       state_class=TOTAL, icon="mdi:run-fast"),
    _d("intensity_minutes_goal", "daily", _summary("intensityMinutesGoal"), unit=MINUTES,
       category=EntityCategory.DIAGNOSTIC, enabled=False),
    _d("floors_ascended", "daily", _summary("floorsAscended", digits=0), state_class=TOTAL, icon="mdi:stairs-up"),
    _d("floors_descended", "daily", _summary("floorsDescended", digits=0), state_class=TOTAL, icon="mdi:stairs-down"),
    _d("floors_goal", "daily", _summary("userFloorsAscendedGoal"), category=EntityCategory.DIAGNOSTIC, enabled=False),
    _d("highly_active_time", "daily", _summary("highlyActiveSeconds"), unit=SECONDS, device_class=DURATION,
       state_class=TOTAL, enabled=False),
    _d("active_time", "daily", _summary("activeSeconds"), unit=SECONDS, device_class=DURATION,
       state_class=TOTAL, enabled=False),
    _d("sedentary_time", "daily", _summary("sedentarySeconds"), unit=SECONDS, device_class=DURATION,
       state_class=TOTAL, enabled=False),
    _d("heart_rate_resting", "daily", _summary("restingHeartRate"), unit=BPM, icon="mdi:heart-pulse"),
    _d("heart_rate_resting_7d", "daily", _summary("lastSevenDaysAvgRestingHeartRate"), unit=BPM, icon="mdi:heart-pulse"),
    _d("heart_rate_min", "daily", _summary("minHeartRate"), unit=BPM, icon="mdi:heart-pulse"),
    _d("heart_rate_max", "daily", _summary("maxHeartRate"), unit=BPM, icon="mdi:heart-pulse",
       attrs=_hr_intraday, intraday=True),
    _d("stress_average", "daily", _summary("averageStressLevel"), icon="mdi:emoticon-neutral"),
    _d("stress_max", "daily", _summary("maxStressLevel"), enabled=False),
    _d("stress_qualifier", "daily", _stress_qualifier, labels="stress"),
    _d("stress_rest_time", "daily", _summary("restStressDuration"), unit=SECONDS, device_class=DURATION, enabled=False),
    _d("stress_low_time", "daily", _summary("lowStressDuration"), unit=SECONDS, device_class=DURATION, enabled=False),
    _d("stress_medium_time", "daily", _summary("mediumStressDuration"), unit=SECONDS, device_class=DURATION, enabled=False),
    _d("stress_high_time", "daily", _summary("highStressDuration"), unit=SECONDS, device_class=DURATION, enabled=False),
    _d("body_battery", "daily", _summary("bodyBatteryMostRecentValue"), unit=PERCENTAGE, icon="mdi:battery-heart-variant",
       attrs=_body_battery_intraday, intraday=True),
    _d("body_battery_level", "daily", _body_battery_level, labels="body_battery_level", state_class=NO_CLASS,
       attrs=_body_battery_events, enabled=False, icon="mdi:battery-heart-variant"),
    _d("body_battery_high", "daily", _summary("bodyBatteryHighestValue"), unit=PERCENTAGE, icon="mdi:battery-heart-variant"),
    _d("body_battery_low", "daily", _summary("bodyBatteryLowestValue"), unit=PERCENTAGE, icon="mdi:battery-heart-variant"),
    _d("body_battery_charged", "daily", _summary("bodyBatteryChargedValue"), unit=PERCENTAGE, state_class=TOTAL,
       enabled=False),
    _d("body_battery_drained", "daily", _summary("bodyBatteryDrainedValue"), unit=PERCENTAGE, state_class=TOTAL,
       enabled=False),
    _d("body_battery_at_wake", "daily", _summary("bodyBatteryAtWakeTime"), unit=PERCENTAGE, enabled=False),
    _d("body_battery_during_sleep", "daily", _summary("bodyBatteryDuringSleep"), unit=PERCENTAGE, enabled=False),
    _d("spo2_average", "daily", number_at("spo2", "averageSpO2"), unit=PERCENTAGE, icon="mdi:water-percent",
       attrs=_spo2_intraday, intraday=True),
    _d("spo2_lowest", "daily", number_at("spo2", "lowestSpO2"), unit=PERCENTAGE, icon="mdi:water-percent"),
    _d("spo2_latest", "daily", number_at("spo2", "latestSpO2"), unit=PERCENTAGE, icon="mdi:water-percent"),
    _d("spo2_7d", "daily", number_at("spo2", "lastSevenDaysAvgSpO2"), unit=PERCENTAGE, enabled=False),
    _d("stress_percentage", "daily", _summary("stressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("stress_rest_percentage", "daily", _summary("restStressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("stress_activity_percentage", "daily", _summary("activityStressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("stress_low_percentage", "daily", _summary("lowStressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("stress_medium_percentage", "daily", _summary("mediumStressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("stress_high_percentage", "daily", _summary("highStressPercentage"), unit=PERCENTAGE, enabled=False),
    _d("altitude_average", "daily", _summary("averageMonitoringEnvironmentAltitude"), unit="m",
       device_class=SensorDeviceClass.DISTANCE, enabled=False, icon="mdi:altimeter"),
    _d("respiration_highest", "daily", _summary("highestRespirationValue"), unit="brpm", enabled=False, icon="mdi:lungs"),
    _d("respiration_lowest", "daily", _summary("lowestRespirationValue"), unit="brpm", enabled=False, icon="mdi:lungs"),
    _d("heart_rate_avg_min", "daily", _summary("minAvgHeartRate"), unit=BPM, enabled=False, icon="mdi:heart-pulse"),
    _d("heart_rate_avg_max", "daily", _summary("maxAvgHeartRate"), unit=BPM, enabled=False, icon="mdi:heart-pulse"),
    _d("respiration_waking", "daily", _summary("avgWakingRespirationValue"), unit="brpm", enabled=False,
       icon="mdi:lungs"),
    _d("respiration_latest", "daily", _summary("latestRespirationValue"), unit="brpm", enabled=False,
       icon="mdi:lungs"),
    _d("hydration", "daily", item_number("hydration", "valueInML"), unit=UnitOfVolume.MILLILITERS,
       device_class=SensorDeviceClass.VOLUME, state_class=TOTAL, icon="mdi:cup-water"),
    _d("hydration_goal", "daily", item_number("hydration", "goalInML"), unit=UnitOfVolume.MILLILITERS,
       device_class=SensorDeviceClass.VOLUME, state_class=NO_CLASS, category=EntityCategory.DIAGNOSTIC, enabled=False),
    _d("hydration_sweat_loss", "daily", item_number("hydration", "sweatLossInML"), unit=UnitOfVolume.MILLILITERS,
       device_class=SensorDeviceClass.VOLUME, state_class=NO_CLASS, enabled=False),
    _d("last_sync", "daily", timestamp_at("summary", "lastSyncTimestampGMT"), device_class=TIMESTAMP,
       state_class=NO_CLASS, category=EntityCategory.DIAGNOSTIC, icon="mdi:watch-vibrate"),
    # ---- Sleep and HRV (group "sleep") ------------------------------------------------
    _d("sleep_duration", "sleep", number_at("sleep", "sleepTimeSeconds"), unit=SECONDS, device_class=DURATION,
       state_class=NO_CLASS, icon="mdi:sleep"),
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
    _d("sleep_score", "sleep", _sleep_score("overall"), attrs=_sleep_score_attrs("overall"), icon="mdi:sleep"),
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
    _d("sleep_heart_rate", "sleep", number_at("sleep", "avgHeartRate", digits=0), unit=BPM, enabled=False),
    _d("sleep_stress", "sleep", number_at("sleep", "avgSleepStress", digits=1), enabled=False),
    _d("sleep_spo2_average", "sleep", number_at("sleep", "averageSpO2Value"), unit=PERCENTAGE, enabled=False),
    _d("sleep_spo2_lowest", "sleep", number_at("sleep", "lowestSpO2Value"), unit=PERCENTAGE, enabled=False),
    _d("sleep_respiration_average", "sleep", number_at("sleep", "averageRespirationValue"), unit="brpm", enabled=False),
    _d("sleep_need", "sleep", number_at("sleep", "sleepNeed", "actual"), unit=MINUTES, state_class=NO_CLASS,
       enabled=False),
    _d("sleep_need_next", "sleep", number_at("sleep", "nextSleepNeed", "actual"), unit=MINUTES, state_class=NO_CLASS,
       enabled=False),
    _d("sleep_feedback", "sleep", text_at("sleep", "sleepScoreFeedback"), labels="sleep_feedback", state_class=NO_CLASS, enabled=False),
    _d("sleep_insight", "sleep", text_at("sleep", "sleepScoreInsight"), labels="sleep_insight", state_class=NO_CLASS, enabled=False),
    _d("sleep_personal_insight", "sleep", text_at("sleep", "sleepScorePersonalizedInsight"), labels="sleep_personal_insight",
       state_class=NO_CLASS, enabled=False),
    _d("sleep_alignment", "sleep", text_at("sleep", "sleepAlignment", "status"), labels="sleep_alignment",
       state_class=NO_CLASS, attrs=_sleep_alignment_attrs, enabled=False, icon="mdi:sleep"),
    _d("sleep_breathing_disruption", "sleep", text_at("sleep", "breathingDisruptionSeverity"), state_class=NO_CLASS,
       enabled=False),
    _d("hrv_last_night", "sleep", _hrv("lastNightAvg"), unit="ms", icon="mdi:heart-flash", attrs=_hrv_attrs),
    _d("hrv_weekly", "sleep", _hrv("weeklyAvg"), unit="ms", icon="mdi:heart-flash"),
    _d("hrv_5min_high", "sleep", _hrv("lastNight5MinHigh"), unit="ms", enabled=False),
    _d("hrv_status", "sleep", _hrv_text("status"), labels="hrv_status"),
    _d("hrv_feedback", "sleep", _hrv_text("feedbackPhrase"), labels="hrv_feedback", state_class=NO_CLASS, enabled=False),
    # ---- Body (group "body") ----------------------------------------------------------
    _d("weight", "body", weight_at("weight", scale=1000, digits=2), unit=UnitOfMass.KILOGRAMS,
       device_class=SensorDeviceClass.WEIGHT, attrs=_weight_attrs, icon="mdi:scale-bathroom"),
    _d("bmi", "body", weight_at("bmi", digits=1), icon="mdi:human"),
    _d("body_fat", "body", weight_at("bodyFat", digits=1, zero_is_none=True), unit=PERCENTAGE, icon="mdi:percent"),
    _d("body_water", "body", weight_at("bodyWater", digits=1, zero_is_none=True), unit=PERCENTAGE, icon="mdi:water-percent"),
    _d("muscle_mass", "body", weight_at("muscleMass", scale=1000, digits=2, zero_is_none=True), unit=UnitOfMass.KILOGRAMS,
       device_class=SensorDeviceClass.WEIGHT),
    _d("bone_mass", "body", weight_at("boneMass", scale=1000, digits=2, zero_is_none=True), unit=UnitOfMass.KILOGRAMS,
       device_class=SensorDeviceClass.WEIGHT),
    _d("visceral_fat", "body", weight_at("visceralFat"), enabled=False),
    _d("metabolic_age", "body", weight_at("metabolicAge", digits=0), unit="a", enabled=False),
    _d("fitness_age", "body", number_at("fitness_age", "fitnessAge", digits=1), unit="a", attrs=_fitness_age_attrs,
       icon="mdi:human-handsup"),
    _d("fitness_age_achievable", "body", number_at("fitness_age", "achievableFitnessAge", digits=1), unit="a",
       enabled=False),
    _d("chronological_age", "body", number_at("fitness_age", "chronologicalAge"), unit="a", enabled=False,
       category=EntityCategory.DIAGNOSTIC),
    # ---- Activities (group "activities") ----------------------------------------------
    _d("last_activity", "activities", activity_text("activityName"), state_class=NO_CLASS, attrs=_activity_attrs,
       icon="mdi:run"),
    _d("last_activity_type", "activities", activity_text("activityType", "typeKey"), labels="activity_type"),
    _d("last_activity_start", "activities", activity_timestamp("startTimeGMT"), device_class=TIMESTAMP,
       state_class=NO_CLASS),
    _d("last_activity_distance", "activities", activity_number("distance"), unit=UnitOfLength.METERS,
       device_class=SensorDeviceClass.DISTANCE, state_class=NO_CLASS, precision=0),
    _d("last_activity_duration", "activities", activity_number("duration"), unit=SECONDS, device_class=DURATION,
       state_class=NO_CLASS),
    _d("last_activity_calories", "activities", activity_number("calories", digits=0), unit=KCAL, state_class=NO_CLASS),
    _d("last_activity_avg_hr", "activities", activity_number("averageHR", digits=0), unit=BPM, state_class=NO_CLASS),
    _d("last_activity_max_hr", "activities", activity_number("maxHR", digits=0), unit=BPM, state_class=NO_CLASS),
    _d("last_activity_aerobic_te", "activities", activity_number("aerobicTrainingEffect", digits=1),
       state_class=NO_CLASS, enabled=False),
    _d("last_activity_anaerobic_te", "activities", activity_number("anaerobicTrainingEffect", digits=1),
       state_class=NO_CLASS, enabled=False),
    _d("last_activity_load", "activities", activity_number("activityTrainingLoad", digits=0), state_class=NO_CLASS,
       enabled=False),
    _d("last_activity_vo2max", "activities", activity_number("vO2MaxValue", digits=1), state_class=NO_CLASS,
       enabled=False),
    _d("last_activity_elevation", "activities", activity_number("elevationGain", digits=0), unit=UnitOfLength.METERS,
       device_class=SensorDeviceClass.DISTANCE, state_class=NO_CLASS, enabled=False),
    _d("wellness_activities", "activities", lambda d: _count(d, "wellness_activities"), state_class=NO_CLASS,
       enabled=False),
    # ---- Profile (group "profile") ----------------------------------------------------
    _d("account", "profile", text_at("profile", "displayName"), state_class=NO_CLASS,
       category=EntityCategory.DIAGNOSTIC, attrs=_account_attrs, icon="mdi:account"),
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


def sensors_to_prune(data_by_group: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """Sensors that are empty although their endpoint answered.

    Endpoints that returned nothing at all (for example last night's sleep early
    in the morning) are left alone, since their sensors will fill in later.
    """
    keys: set[str] = set()
    for description in SENSOR_DESCRIPTIONS:
        if not description.entity_registry_enabled_default or description.entity_category:
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
    entities.append(GarminKeyExpirySensor(runtime.coordinators["profile"], entry))
    async_add_entities(entities)


class GarminSensor(CoordinatorEntity[GarminCoordinator], RestoreSensor):
    """A sensor reading one value out of its coordinator's data.

    Sleep and body values keep their last known value (also across restarts) while Garmin
    returns nothing; the attributes then say so.
    """

    _attr_has_entity_name = True
    entity_description: GarminSensorDescription
    _unrecorded_attributes = frozenset({"values", "hourly_values", "components"})

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
        if state is not None:
            self._last_seen = state.attributes.get("last_seen")

    @property
    def native_value(self) -> StateType:
        """The current value, or the last known one for sleep and body values."""
        current = self.entity_description.value_fn(self.coordinator.data) if self.coordinator.data else None
        if not self._keep:
            return current
        if current is not None:
            if current != self._last_value:
                self._last_seen = dt_util.utcnow().isoformat(timespec="seconds")
            self._last_value = current
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
        if self._keep and self._last_value is not None:
            fresh = bool(self.coordinator.data) and description.value_fn(self.coordinator.data) is not None
            attrs["last_seen"] = self._last_seen
            attrs["held_value"] = not fresh
        return attrs or None


class GarminKeyExpirySensor(CoordinatorEntity[GarminCoordinator], SensorEntity):
    """When the Personal API key runs out (from the validity chosen at setup)."""

    _attr_has_entity_name = True
    _attr_translation_key = "key_expires"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GarminCoordinator, entry: GarminConfigEntry) -> None:
        """Set up the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_key_expires"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> Any:
        """Expiry time of the API key."""
        return key_expires_at(self._entry)
