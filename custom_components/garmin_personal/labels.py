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
