"""Readable names for the fixed word lists Garmin uses as sensor values.

Garmin reports ratings and statuses as keys such as ``FAIR`` or ``mountain_biking``.
The sensors keep that key (lower case) as their state and Home Assistant shows the
translation below. A key that is not listed is still shown as it is, never hidden.
"""

from __future__ import annotations

# list name -> {key: (English, German)}
LABELS: dict[str, dict[str, tuple[str, str]]] = {
    "rating": {
        "excellent": ("Excellent", "Ausgezeichnet"),
        "good": ("Good", "Gut"),
        "fair": ("Fair", "Mittelmäßig"),
        "poor": ("Poor", "Schlecht"),
    },
    "sleep_feedback": {
        # Only keys seen in real responses; the words of the key are translated literally.
        "positive_recovering": ("Positive: recovering", "Positiv: erholsam"),
        "positive_refreshing": ("Positive: refreshing", "Positiv: erfrischend"),
        "positive_calm": ("Positive: calm", "Positiv: ruhig"),
        "positive_short_but_recovering": ("Positive: short but recovering", "Positiv: kurz, aber erholsam"),
        "positive_short_but_refreshing": ("Positive: short but refreshing", "Positiv: kurz, aber erfrischend"),
        "positive_long_and_continuous": ("Positive: long and continuous", "Positiv: lang und durchgehend"),
        "positive_long_and_refreshing": ("Positive: long and refreshing", "Positiv: lang und erfrischend"),
        "positive_long_and_deep": ("Positive: long and deep", "Positiv: lang und tief"),
        "positive_continuous": ("Positive: continuous", "Positiv: durchgehend"),
        "positive_optimal_structure": ("Positive: optimal structure", "Positiv: optimale Struktur"),
        "negative_discontinuous": ("Negative: discontinuous", "Negativ: unterbrochen"),
        "negative_light": ("Negative: light", "Negativ: zu leicht"),
        "negative_short_and_poor_structure": ("Negative: short and poor structure", "Negativ: kurz und schlechte Struktur"),
        "negative_not_enough_rem": ("Negative: not enough REM", "Negativ: zu wenig REM-Schlaf"),
    },
    "sleep_insight": {
        "positive_restful_day": ("Positive: restful day", "Positiv: erholsamer Tag"),
        "positive_exercise": ("Positive: exercise", "Positiv: Training"),
        "positive_restful_evening": ("Positive: restful evening", "Positiv: erholsamer Abend"),
        "positive_late_bed_time": ("Positive: late bed time", "Positiv: späte Schlafenszeit"),
        "positive_acclimatization_in_progress": ("Positive: acclimatization in progress", "Positiv: Akklimatisierung läuft"),
        "negative_strenuous_exercise": ("Negative: strenuous exercise", "Negativ: anstrengendes Training"),
        "negative_late_strenuous_exercise": ("Negative: late strenuous exercise", "Negativ: spätes anstrengendes Training"),
        "negative_acclimatization_in_progress": ("Negative: acclimatization in progress", "Negativ: Akklimatisierung läuft"),
        "none": ("None", "Keine"),
    },
    "hrv_status": {
        "balanced": ("Balanced", "Ausgeglichen"),
        "unbalanced": ("Unbalanced", "Unausgeglichen"),
        "low": ("Low", "Niedrig"),
        "poor": ("Poor", "Schlecht"),
        "none": ("No status", "Kein Status"),
    },
    "stress": {
        "calm": ("Calm", "Ruhig"),
        "balanced": ("Balanced", "Ausgeglichen"),
        "stressful": ("Stressful", "Stressig"),
        "very_stressful": ("Very stressful", "Sehr stressig"),
        "unknown": ("Unknown", "Unbekannt"),
    },
    "activity_type": {
        "running": ("Running", "Laufen"),
        "trail_running": ("Trail running", "Trailrunning"),
        "treadmill_running": ("Treadmill running", "Laufband"),
        "walking": ("Walking", "Gehen"),
        "hiking": ("Hiking", "Wandern"),
        "cycling": ("Cycling", "Radfahren"),
        "road_biking": ("Road cycling", "Rennrad"),
        "gravel_cycling": ("Gravel cycling", "Gravel"),
        "mountain_biking": ("Mountain biking", "Mountainbike"),
        "e_bike_fitness": ("E-bike", "E-Bike"),
        "e_bike_mountain": ("E-mountain bike", "E-Mountainbike"),
        "indoor_cycling": ("Indoor cycling", "Indoor-Radfahren"),
        "virtual_ride": ("Virtual ride", "Virtuelle Fahrt"),
        "strength_training": ("Strength training", "Krafttraining"),
        "indoor_cardio": ("Indoor cardio", "Cardio indoor"),
        "hiit": ("HIIT", "HIIT"),
        "yoga": ("Yoga", "Yoga"),
        "pilates": ("Pilates", "Pilates"),
        "elliptical": ("Elliptical", "Crosstrainer"),
        "stair_stepper": ("Stair stepper", "Treppensteiger"),
        "rowing": ("Rowing", "Rudern"),
        "indoor_rowing": ("Indoor rowing", "Rudergerät"),
        "swimming": ("Swimming", "Schwimmen"),
        "lap_swimming": ("Pool swimming", "Bahnenschwimmen"),
        "open_water_swimming": ("Open water swimming", "Freiwasserschwimmen"),
        "cross_country_skiing_ws": ("Cross-country skiing", "Skilanglauf"),
        "resort_skiing_snowboarding_ws": ("Skiing / snowboarding", "Ski / Snowboard"),
        "backcountry_skiing_snowboarding_ws": ("Backcountry skiing", "Skitour"),
        "inline_skating": ("Inline skating", "Inlineskaten"),
        "stand_up_paddleboarding_v2": ("Stand-up paddling", "Stand-up-Paddling"),
        "kayaking_v2": ("Kayaking", "Kajak"),
        "golf": ("Golf", "Golf"),
        "tennis_v2": ("Tennis", "Tennis"),
        "multi_sport": ("Multisport", "Multisport"),
        "other": ("Other", "Sonstiges"),
    },
}

# "personal insight": the key is built from a topic, a direction, the sleep quality and a context.
# Only combinations seen in real responses are listed; the words are translated literally.
_TOPIC = {
    "STRESS": ("Stress", "Stress"), "HARD_EXERCISE": ("Hard exercise", "Hartes Training"),
    "MOD_EXERCISE": ("Moderate exercise", "Moderates Training"), "GENERAL": ("General", "Allgemein"),
    "RHYTHM": ("Rhythm", "Rhythmus"), "ALTITUDE": ("Altitude", "Höhe"),
}
_DIR = {"POS": ("positive", "positiv"), "NEG": ("negative", "negativ")}
_SLEEP = {
    "EXCELLENT_OR_GOOD_SLEEP": ("excellent or good sleep", "ausgezeichneter oder guter Schlaf"),
    "FAIR_OR_POOR_SLEEP": ("fair or poor sleep", "mittelmäßiger oder schlechter Schlaf"),
    "FAIR_SLEEP": ("fair sleep", "mittelmäßiger Schlaf"), "POOR_SLEEP": ("poor sleep", "schlechter Schlaf"),
}
_CONTEXT = {
    "RESTFUL_EVENING": ("restful evening", "erholsamer Abend"), "RESTFUL_DAY": ("restful day", "erholsamer Tag"),
    "VERY_RESTFUL_DAY": ("very restful day", "sehr erholsamer Tag"),
    "HARD_CLOSE_BED": ("hard close to bedtime", "hart kurz vor dem Schlafen"),
    "HARD_DURING_DAY": ("hard during the day", "hart im Tagesverlauf"),
    "VIGOROUS_CLOSE_BED": ("vigorous close to bedtime", "intensiv kurz vor dem Schlafen"),
    "VIGOROUS_DURING_DAY": ("vigorous during the day", "intensiv im Tagesverlauf"),
    "VIGOROUS_DURING_DAY_OUTDOOR": ("vigorous outdoors during the day", "intensiv draußen im Tagesverlauf"),
    "MODERATE_CLOSE_BED": ("moderate close to bedtime", "moderat kurz vor dem Schlafen"),
    "MODERATE_DURING_DAY": ("moderate during the day", "moderat im Tagesverlauf"),
    "REALLY_LATE_TIMING": ("really late timing", "sehr später Zeitpunkt"),
}
_SEEN_PERSONAL = [
    "STRESS_POS_EXCELLENT_OR_GOOD_SLEEP_RESTFUL_EVENING", "HARD_EXERCISE_NEG_FAIR_OR_POOR_SLEEP_HARD_CLOSE_BED",
    "HARD_EXERCISE_NEG_FAIR_OR_POOR_SLEEP_HARD_DURING_DAY", "GENERAL_POS_FAIR_OR_POOR_SLEEP",
    "STRESS_POS_FAIR_OR_POOR_SLEEP_RESTFUL_DAY", "MOD_EXERCISE_POS_EXCELLENT_OR_GOOD_SLEEP_VIGOROUS_CLOSE_BED",
    "GENERAL_NEG_FAIR_OR_POOR_SLEEP", "RHYTHM_NEG_FAIR_SLEEP_REALLY_LATE_TIMING",
    "MOD_EXERCISE_POS_EXCELLENT_OR_GOOD_SLEEP_VIGOROUS_DURING_DAY", "ALTITUDE_NEG_POOR_SLEEP",
    "ALTITUDE_POS_FAIR_SLEEP", "HARD_EXERCISE_POS_EXCELLENT_OR_GOOD_SLEEP_HARD_CLOSE_BED",
    "STRESS_POS_FAIR_OR_POOR_SLEEP_RESTFUL_EVENING", "MOD_EXERCISE_POS_EXCELLENT_OR_GOOD_SLEEP_MODERATE_DURING_DAY",
    "MOD_EXERCISE_POS_EXCELLENT_OR_GOOD_SLEEP_VIGOROUS_DURING_DAY_OUTDOOR",
    "STRESS_POS_EXCELLENT_OR_GOOD_SLEEP_RESTFUL_DAY", "MOD_EXERCISE_POS_EXCELLENT_OR_GOOD_SLEEP_MODERATE_CLOSE_BED",
    "STRESS_POS_EXCELLENT_OR_GOOD_SLEEP_VERY_RESTFUL_DAY", "GENERAL_POS_EXCELLENT_OR_GOOD_SLEEP",
]


def _personal() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {"not_available": ("Not available", "Nicht verfügbar")}
    for key in _SEEN_PERSONAL:
        for topic in sorted(_TOPIC, key=len, reverse=True):
            if key.startswith(topic + "_"):
                rest = key[len(topic) + 1:]
                break
        else:
            continue
        direction, rest = rest.split("_", 1)
        for sleep in sorted(_SLEEP, key=len, reverse=True):
            if rest == sleep or rest.startswith(sleep + "_"):
                ctx = rest[len(sleep) + 1:]
                break
        else:
            continue
        en = [f"{_TOPIC[topic][0]} {_DIR[direction][0]}: {_SLEEP[sleep][0]}"]
        de = [f"{_TOPIC[topic][1]} {_DIR[direction][1]}: {_SLEEP[sleep][1]}"]
        if ctx:
            if ctx not in _CONTEXT:
                continue
            en.append(_CONTEXT[ctx][0])
            de.append(_CONTEXT[ctx][1])
        out[key.lower()] = (", ".join(en), ", ".join(de))
    return out


LABELS["sleep_personal_insight"] = _personal()
