"""Generate strings.json and translations/{en,de}.json (run from the repo root)."""

import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "garmin_personal"

N = {
 "steps": ("Steps", "Schritte"), "step_goal": ("Step goal", "Schrittziel"),
 "distance": ("Distance", "Distanz"), "total_calories": ("Total calories", "Gesamtkalorien"),
 "active_calories": ("Active calories", "Aktive Kalorien"), "resting_calories": ("Resting calories", "Ruhekalorien"),
 "consumed_calories": ("Consumed calories", "Aufgenommene Kalorien"), "remaining_calories": ("Remaining calories", "Verbleibende Kalorien"),
 "moderate_intensity_minutes": ("Moderate intensity minutes", "Intensitätsminuten (moderat)"),
 "vigorous_intensity_minutes": ("Vigorous intensity minutes", "Intensitätsminuten (hoch)"),
 "intensity_minutes_goal": ("Intensity minutes goal", "Intensitätsminuten-Ziel"),
 "floors_ascended": ("Floors ascended", "Stockwerke aufwärts"), "floors_descended": ("Floors descended", "Stockwerke abwärts"),
 "floors_goal": ("Floors goal", "Stockwerke-Ziel"), "highly_active_time": ("Highly active time", "Hochaktive Zeit"),
 "active_time": ("Active time", "Aktive Zeit"), "sedentary_time": ("Sedentary time", "Sitzzeit"),
 "heart_rate_resting": ("Resting heart rate", "Ruhepuls"), "heart_rate_resting_7d": ("Resting heart rate (7 days)", "Ruhepuls (7 Tage)"),
 "heart_rate_min": ("Minimum heart rate", "Minimaler Puls"), "heart_rate_max": ("Maximum heart rate", "Maximaler Puls"),
 "stress_average": ("Average stress", "Durchschnittlicher Stress"), "stress_max": ("Maximum stress", "Maximaler Stress"),
 "stress_qualifier": ("Stress level", "Stressstufe"), "stress_rest_time": ("Rest stress time", "Zeit in Ruhe (Stress)"),
 "stress_low_time": ("Low stress time", "Zeit mit niedrigem Stress"), "stress_medium_time": ("Medium stress time", "Zeit mit mittlerem Stress"),
 "stress_high_time": ("High stress time", "Zeit mit hohem Stress"),
 "stress_percentage": ("Stress share", "Stressanteil"), "stress_rest_percentage": ("Rest stress share", "Anteil Ruhe (Stress)"),
 "stress_activity_percentage": ("Activity share (stress)", "Aktivitätsanteil (Stress)"),
 "stress_low_percentage": ("Low stress share", "Anteil mit niedrigem Stress"), "stress_medium_percentage": ("Medium stress share", "Anteil mit mittlerem Stress"),
 "stress_high_percentage": ("High stress share", "Anteil mit hohem Stress"),
 "altitude_average": ("Average altitude", "Durchschnittliche Höhe"),
 "respiration_highest": ("Highest respiration", "Höchste Atemfrequenz"), "respiration_lowest": ("Lowest respiration", "Niedrigste Atemfrequenz"),
 "heart_rate_avg_min": ("Lowest average heart rate", "Niedrigster Durchschnittspuls"),
 "heart_rate_avg_max": ("Highest average heart rate", "Höchster Durchschnittspuls"),
 "sleep_alignment": ("Sleep alignment", "Schlafausrichtung"), "body_battery_level": ("Body Battery level", "Body-Battery-Stufe"),
 "body_battery": ("Body Battery", "Body Battery"), "body_battery_high": ("Body Battery highest", "Body-Battery-Höchstwert"),
 "body_battery_low": ("Body Battery lowest", "Body-Battery-Tiefstwert"), "body_battery_charged": ("Body Battery charged", "Body Battery: geladen"),
 "body_battery_drained": ("Body Battery drained", "Body Battery: verbraucht"), "body_battery_at_wake": ("Body Battery at wake-up", "Body Battery beim Aufwachen"),
 "body_battery_during_sleep": ("Body Battery during sleep", "Body Battery im Schlaf"),
 "spo2_average": ("Average SpO2", "Durchschnittliche SpO2"), "spo2_lowest": ("Lowest SpO2", "Niedrigste SpO2"),
 "spo2_latest": ("Latest SpO2", "Aktuelle SpO2"), "spo2_7d": ("SpO2 (7 days)", "SpO2 (7 Tage)"),
 "respiration_waking": ("Respiration (awake)", "Atemfrequenz (wach)"), "respiration_latest": ("Respiration (latest)", "Atemfrequenz (aktuell)"),
 "hydration": ("Hydration", "Flüssigkeitszufuhr"), "hydration_goal": ("Hydration goal", "Trinkziel"),
 "hydration_sweat_loss": ("Sweat loss", "Schweißverlust"), "last_sync": ("Last sync", "Letzte Synchronisation"),
 "sleep_duration": ("Sleep duration", "Schlafdauer"), "sleep_deep": ("Deep sleep", "Tiefschlaf"),
 "sleep_light": ("Light sleep", "Leichtschlaf"), "sleep_rem": ("REM sleep", "REM-Schlaf"), "sleep_awake": ("Awake time", "Wachzeit"),
 "nap_duration": ("Nap duration", "Nickerchen-Dauer"), "sleep_score": ("Sleep score", "Schlafwert"),
 "sleep_score_duration": ("Sleep score: duration", "Schlafwert: Dauer"), "sleep_score_stress": ("Sleep score: stress", "Schlafwert: Stress"),
 "sleep_score_restlessness": ("Sleep score: restlessness", "Schlafwert: Unruhe"), "sleep_score_awake_count": ("Sleep score: awakenings", "Schlafwert: Aufwachphasen"),
 "sleep_score_rem": ("Sleep score: REM", "Schlafwert: REM"), "sleep_score_light": ("Sleep score: light", "Schlafwert: Leichtschlaf"),
 "sleep_score_deep": ("Sleep score: deep", "Schlafwert: Tiefschlaf"), "sleep_start": ("Sleep start", "Schlafbeginn"),
 "sleep_end": ("Sleep end", "Schlafende"), "sleep_awake_count": ("Awakenings", "Anzahl Aufwachphasen"),
 "sleep_heart_rate": ("Sleep heart rate", "Puls im Schlaf"), "sleep_stress": ("Sleep stress", "Stress im Schlaf"),
 "sleep_spo2_average": ("Sleep SpO2 average", "SpO2 im Schlaf (Durchschnitt)"), "sleep_spo2_lowest": ("Sleep SpO2 lowest", "SpO2 im Schlaf (niedrigster Wert)"),
 "sleep_respiration_average": ("Sleep respiration", "Atemfrequenz im Schlaf (Durchschnitt)"), "sleep_need": ("Sleep need", "Schlafbedarf"),
 "sleep_need_next": ("Next sleep need", "Nächster Schlafbedarf"), "sleep_feedback": ("Sleep feedback", "Schlaf-Feedback"),
 "sleep_insight": ("Sleep insight", "Schlaf-Einblick"), "sleep_personal_insight": ("Personal sleep insight", "Persönlicher Schlaf-Einblick"), "sleep_breathing_disruption": ("Breathing disruption", "Atemstörungen"),
 "hrv_last_night": ("HRV last night", "HRV letzte Nacht"), "hrv_weekly": ("HRV weekly average", "HRV-Wochendurchschnitt"),
 "hrv_5min_high": ("HRV 5 min high", "HRV 5-Min-Höchstwert"), "hrv_status": ("HRV status", "HRV-Status"),
 "hrv_feedback": ("HRV feedback", "HRV-Feedback"),
 "weight": ("Weight", "Gewicht"), "bmi": ("BMI", "BMI"), "body_fat": ("Body fat", "Körperfett"),
 "body_water": ("Body water", "Körperwasser"), "muscle_mass": ("Muscle mass", "Muskelmasse"), "bone_mass": ("Bone mass", "Knochenmasse"),
 "visceral_fat": ("Visceral fat", "Viszerales Fett"), "metabolic_age": ("Metabolic age", "Stoffwechselalter"),
 "fitness_age": ("Fitness age", "Fitnessalter"), "fitness_age_achievable": ("Achievable fitness age", "Erreichbares Fitnessalter"),
 "chronological_age": ("Chronological age", "Tatsächliches Alter"),
 "last_activity": ("Last activity", "Letzte Aktivität"), "last_activity_type": ("Last activity type", "Letzte Aktivität: Typ"),
 "last_activity_start": ("Last activity start", "Letzte Aktivität: Beginn"), "last_activity_distance": ("Last activity distance", "Letzte Aktivität: Distanz"),
 "last_activity_duration": ("Last activity duration", "Letzte Aktivität: Dauer"), "last_activity_calories": ("Last activity calories", "Letzte Aktivität: Kalorien"),
 "last_activity_avg_hr": ("Last activity average heart rate", "Letzte Aktivität: Durchschnittspuls"), "last_activity_max_hr": ("Last activity maximum heart rate", "Letzte Aktivität: Maximaler Puls"),
 "last_activity_aerobic_te": ("Last activity aerobic training effect", "Letzte Aktivität: aerober Trainingseffekt"),
 "last_activity_anaerobic_te": ("Last activity anaerobic training effect", "Letzte Aktivität: anaerober Trainingseffekt"),
 "last_activity_load": ("Last activity training load", "Letzte Aktivität: Trainingsbelastung"),
 "last_activity_vo2max": ("Last activity VO2max", "Letzte Aktivität: VO2max"),
 "last_activity_elevation": ("Last activity elevation gain", "Letzte Aktivität: Höhenmeter (Anstieg)"),
 "wellness_activities": ("Wellness activities today", "Wellness-Aktivitäten heute"),
 "account": ("Account", "Konto"), "hr_max_used": ("Maximum heart rate (set)", "Maximaler Puls (eingestellt)"),
 "hr_resting_used": ("Resting heart rate (set)", "Ruhepuls (eingestellt)"),
 "hr_lactate_threshold": ("Lactate threshold heart rate", "Laktatschwelle Puls"),
 "key_expires": ("API key expires", "API-Schlüssel läuft ab"),
 "heart_rate_history": ("Heart rate (history)", "Puls (Verlauf)"),
 "body_battery_history": ("Body Battery (history)", "Body Battery (Verlauf)"),
 "spo2_history": ("SpO2 (history)", "SpO2 (Verlauf)"),
}

# ---------------------------------------------------------------------------
# Data that is added to by hand. The generator only assembles; nothing here is derived from code.
# Format: key -> (English, German). Placeholders such as {error} must appear in both languages.

# Default icon per sensor (icons.json). Sensors without an entry use Home Assistant's default.
ICONS = {
    "heart_rate_history": "heart-pulse",
    "body_battery_history": "battery-clock",
    "spo2_history": "water-percent",
    "steps": "shoe-print",
    "total_calories": "fire",
    "active_calories": "fire",
    "resting_calories": "fire",
    "moderate_intensity_minutes": "run-fast",
    "vigorous_intensity_minutes": "run-fast",
    "floors_ascended": "stairs-up",
    "floors_descended": "stairs-down",
    "heart_rate_resting": "heart-pulse",
    "heart_rate_resting_7d": "heart-pulse",
    "heart_rate_min": "heart-pulse",
    "heart_rate_max": "heart-pulse",
    "stress_average": "emoticon-neutral",
    "body_battery": "battery-heart-variant",
    "body_battery_level": "battery-heart-variant",
    "body_battery_high": "battery-heart-variant",
    "body_battery_low": "battery-heart-variant",
    "spo2_average": "water-percent",
    "spo2_lowest": "water-percent",
    "spo2_latest": "water-percent",
    "altitude_average": "altimeter",
    "respiration_highest": "lungs",
    "respiration_lowest": "lungs",
    "heart_rate_avg_min": "heart-pulse",
    "heart_rate_avg_max": "heart-pulse",
    "respiration_waking": "lungs",
    "respiration_latest": "lungs",
    "hydration": "cup-water",
    "last_sync": "watch-vibrate",
    "sleep_duration": "sleep",
    "sleep_score": "sleep",
    "sleep_alignment": "sleep",
    "hrv_last_night": "heart-flash",
    "hrv_weekly": "heart-flash",
    "weight": "scale-bathroom",
    "bmi": "human",
    "body_fat": "percent",
    "body_water": "water-percent",
    "fitness_age": "human-handsup",
    "last_activity": "run",
    "account": "account",
}

# Endpoint names of the service `fetch` (selector.endpoint.options); must equal the options in services.yaml.
ENDPOINT_NAMES: dict[str, tuple[str, str]] = {
    "activities": ("Activities", "Aktivitäten"), "activity": ("Activity", "Aktivität"),
    "activity_workouts": ("Activity workouts", "Workouts einer Aktivität"), "hr_zones": ("Heart rate zones", "Herzfrequenzzonen"),
    "fitness_age": ("Fitness age", "Fitnessalter"), "weight_goals": ("Weight goals", "Gewichtsziele"),
    "hrv": ("HRV", "HRV"), "hrv_summaries": ("HRV summaries", "HRV-Zusammenfassungen"),
    "nutrition": ("Nutrition", "Ernährung"), "menstrual_summary": ("Menstrual summary", "Menstruations-Zusammenfassung"),
    "menstrual_day": ("Menstrual day", "Menstruations-Tagesansicht"), "sleep": ("Sleep", "Schlaf"),
    "sleep_summaries": ("Sleep summaries", "Schlaf-Zusammenfassungen"), "profile": ("Profile", "Profil"),
    "hydration": ("Hydration", "Flüssigkeitszufuhr"), "steps": ("Steps", "Schritte"), "stress": ("Stress", "Stress"),
    "daily_summary": ("Daily summary", "Tageszusammenfassung"), "daily_summaries": ("Daily summaries", "Tageszusammenfassungen"),
    "weights_all": ("All weight entries", "Alle Gewichtseinträge"), "weight_range": ("Weight range", "Gewicht (Zeitraum)"),
    "body_battery": ("Body Battery", "Body Battery"), "spo2": ("SpO2", "SpO2"), "heart_rate": ("Heart rate", "Puls"),
    "wellness_activities": ("Wellness activities", "Wellness-Aktivitäten"),
}

# exceptions.<key>.message, raised as HomeAssistantError(translation_domain=DOMAIN, translation_key=<key>).
EXCEPTIONS: dict[str, tuple[str, str]] = {
    "auth_failed": ("The API key is missing or invalid. Please enter a new key.",
                    "Der API-Schlüssel fehlt oder ist ungültig. Bitte gib einen neuen Schlüssel ein."),
    "no_entry": ("No Garmin account is set up.", "Es ist kein Garmin-Konto eingerichtet."),
    "entry_required": ("Several Garmin accounts exist. Choose one in the Account field: {entries}",
                       "Es gibt mehrere Garmin-Konten. Wähle im Feld Konto eines aus: {entries}"),
    "entry_unknown": ("Unknown Garmin account: {entry_id}", "Unbekanntes Garmin-Konto: {entry_id}"),
    "entry_not_loaded": ("The Garmin account {title} is not loaded. Check the integration under Settings > Devices & services.",
                         "Das Garmin-Konto {title} ist nicht geladen. Prüfe die Integration unter Einstellungen > Geräte & Dienste."),
    "garmin_request_failed": ("The Garmin request failed: {error}", "Die Anfrage an Garmin ist fehlgeschlagen: {error}"),
    "invalid_request": ("Invalid request: {error}", "Ungültige Anfrage: {error}"),
    "invalid_date_range": ("The start date ({start}) is after the end date ({end}). To include today, set the end date explicitly.",
                           "Das Startdatum ({start}) liegt nach dem Enddatum ({end}). Um heute einzuschließen, gib das Enddatum ausdrücklich an."),
    "date_range_too_long": ("The range {start} to {end} is too long (at most {max_days} days).",
                            "Der Zeitraum {start} bis {end} ist zu lang (höchstens {max_days} Tage)."),
    "path_not_allowed": ("{path} is not in an allowed folder. Allow {folder} in allowlist_external_dirs or choose a path under the media folder.",
                         "{path} liegt nicht in einem erlaubten Ordner. Gib {folder} in allowlist_external_dirs frei oder wähle einen Pfad im Medienordner."),
    "path_not_zip": ("The target file {path} must end in .zip.", "Die Zieldatei {path} muss auf .zip enden."),
    "download_failed": ("Could not write {path}: {error}", "{path} konnte nicht geschrieben werden: {error}"),
    "history_write_unsupported": ("Writing the history sensors is not available yet: Home Assistant offers no supported way to store states with past timestamps, and the unsupported route has not been verified. Nothing was requested or written.",
                                  "Das Schreiben der Verlauf-Sensoren ist noch nicht verfügbar: Home Assistant bietet keinen unterstützten Weg, Zustände mit vergangenen Zeitstempeln zu speichern, und der nicht unterstützte Weg ist noch nicht geprüft. Es wurde nichts abgefragt oder geschrieben."),
    "backfill_running": ("An import is already running for {title}.", "Für {title} läuft bereits ein Import."),
}

# <flow>.step.<step>.data_description.<field>; every field must also exist in the step's "data".
DATA_DESCRIPTIONS: dict[tuple[str, str], dict[str, tuple[str, str]]] = {
    ("config", "user"): {
        "name": ("Display name of the account, e.g. a first name. It becomes the device name and part of every entity ID "
                 "(for example sensor.jan_steps if the name is Jan); renaming later does not change existing entity IDs.",
                 "Anzeigename des Kontos, z. B. der Vorname. Er wird Gerätename und Teil aller Entitäts-IDs "
                 "(z. B. sensor.jan_steps bei dem Namen Jan); späteres Umbenennen ändert bestehende IDs nicht."),
        "api_key": ("The key from Garmin Connect (Settings > Personal API key). Garmin shows it only once.",
                    "Der Schlüssel aus Garmin Connect (Einstellungen > Persönlicher API-Schlüssel). Garmin zeigt ihn nur einmal."),
        "key_validity_days": ("The same duration you chose in Garmin when creating the key. Garmin does not report the expiry date; "
                              "it is calculated from this value and only used for the reminder before expiry.",
                              "Dieselbe Dauer, die du beim Erzeugen des Schlüssels in Garmin gewählt hast. Garmin verrät das Ablaufdatum nicht; "
                              "es wird daraus berechnet und nur für die Erinnerung vor dem Ablauf genutzt."),
    },
    ("config", "reauth_confirm"): {
        "api_key": ("The new key from Garmin Connect, created in the same Garmin account.",
                    "Der neue Schlüssel aus Garmin Connect, erzeugt im selben Garmin-Konto."),
        "key_validity_days": ("The duration you chose in Garmin for the new key (preset: your last choice). The expiry date is calculated from it.",
                              "Die Dauer, die du in Garmin für den neuen Schlüssel gewählt hast (vorbelegt: deine letzte Wahl). Das Ablaufdatum wird daraus berechnet."),
    },
    ("config", "reconfigure"): {
        "api_key": ("The new key from Garmin Connect, created in the same Garmin account.",
                    "Der neue Schlüssel aus Garmin Connect, erzeugt im selben Garmin-Konto."),
        "key_validity_days": ("The duration you chose in Garmin for the new key (preset: your last choice). The expiry date is calculated from it.",
                              "Die Dauer, die du in Garmin für den neuen Schlüssel gewählt hast (vorbelegt: deine letzte Wahl). Das Ablaufdatum wird daraus berechnet."),
    },
    ("options", "init"): {
        "daily_interval_minutes": ("How often the daily values are requested. The other data is fetched only after a new watch sync or less often.",
                                   "Wie oft die Tageswerte abgefragt werden. Die übrigen Daten werden nur nach einer neuen Uhr-Synchronisierung oder seltener geholt."),
        "intraday_attributes": ("Adds heart rate, Body Battery and SpO2 series to the sensors as attributes. This makes the state data "
                                "large, requests extra data from Garmin and the series are not stored in the recorder.",
                                "Hängt Puls-, Body-Battery- und SpO2-Verläufe als Attribute an die Sensoren. Das macht die Zustandsdaten "
                                "groß, ruft zusätzliche Daten bei Garmin ab, und die Verläufe werden nicht im Recorder gespeichert."),
        "hourly_statistics": ("After each new watch sync, writes heart rate, Body Battery and SpO2 as hourly values (minimum, maximum, mean "
                              "of each completed hour) into the long-term statistics. Independent of the option above; costs one extra "
                              "request per series and sync (plus one per series for yesterday in the morning).",
                              "Schreibt nach jeder neuen Uhr-Synchronisierung Puls, Body Battery und SpO2 als Stundenwerte (Minimum, Maximum, "
                              "Mittelwert jeder abgeschlossenen Stunde) in die Langzeitstatistik. Unabhängig von der Option darüber; kostet "
                              "je Reihe und Sync eine zusätzliche Anfrage (morgens plus eine je Reihe für gestern)."),
        "sync_stale_hours": ("The binary sensor reports a problem when the last watch sync is older than this many hours.",
                             "Der Binärsensor meldet ein Problem, wenn der letzte Uhr-Sync länger als so viele Stunden her ist."),
    },
}

# Further repair issues: key -> {"title": (en, de), "description": (en, de)} (key_expiring is built in below).
EXTRA_ISSUES: dict[str, dict[str, tuple[str, str]]] = {}

# Extra service fields: service -> field -> {"name": (en, de), "description": (en, de)}; added to the built-in fields.
EXTRA_SERVICE_FIELDS: dict[str, dict[str, dict[str, tuple[str, str]]]] = {}


class GeneratorError(Exception):
    """Raised with a message that says what to fix; the command line prints it and exits with 1."""


def parse_descriptors(source: str) -> list[tuple[str, str | None, bool]]:
    """(key, labels, open_enum) of every ``_d("key", ...)`` call in sensor.py, read from the syntax tree.

    The tree does not depend on line breaks or on Home Assistant, and an argument that is not a
    plain constant is an error instead of being skipped silently.
    """
    out: list[tuple[str, str | None, bool]] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_d"):
            continue
        if not node.args or not (isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            raise GeneratorError(f"sensor.py line {node.lineno}: first argument of _d() must be a string literal")
        key = node.args[0].value
        labels: str | None = None
        open_enum = False
        for kw in node.keywords:
            if kw.arg == "labels":
                if not (isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)):
                    raise GeneratorError(f"sensor.py line {node.lineno}: labels= of sensor {key!r} must be a string literal")
                labels = kw.value.value
            elif kw.arg == "open_enum":
                if not (isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool)):
                    raise GeneratorError(f"sensor.py line {node.lineno}: open_enum= of sensor {key!r} must be True or False")
                open_enum = kw.value.value
        out.append((key, labels, open_enum))
    return out


def load_labels():
    spec = importlib.util.spec_from_file_location("labels", ROOT / "labels.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LABELS


LABELS = load_labels()
_DESCRIPTORS = parse_descriptors((ROOT / "sensor.py").read_text())
if len({k for k, _, _ in _DESCRIPTORS}) != len(_DESCRIPTORS):
    raise GeneratorError("sensor.py: duplicate sensor keys")
keys = [k for k, _, _ in _DESCRIPTORS] + ["key_expires", "heart_rate_history", "body_battery_history", "spo2_history"]
_bad_icons = sorted(k for k in ICONS if k not in keys)
if _bad_icons:
    raise GeneratorError(f"ICONS has entries without a sensor: {_bad_icons}")
# sensor key -> word list name (labels=...)
LABEL_OF = {k: lab for k, lab, _ in _DESCRIPTORS if lab}
_missing = [k for k in keys if k not in N]
_extra = [k for k in N if k not in keys]
if _missing or _extra:
    raise GeneratorError(f"names in N and sensors in sensor.py differ: no name for {_missing}, name without sensor {_extra}")
_unknown_lists = sorted({lab for lab in LABEL_OF.values() if lab not in LABELS})
if _unknown_lists:
    raise GeneratorError(f"labels.py has no word list {_unknown_lists}")


def build(i: int) -> dict:
    de = i == 1
    t = (lambda en, d: d if de else en)
    out = {
        "config": {
            "step": {
                "user": {
                    "title": t("Garmin Connect Personal API", "Garmin Connect Personal API"),
                    "description": t(
                        "Create a key in [Garmin Connect]({key_url}) and paste it here. Garmin shows it only once.",
                        "Erstelle in [Garmin Connect]({key_url}) einen Schlüssel und füge ihn hier ein. Garmin zeigt ihn nur einmal an.",
                    ),
                    "data": {
                        "name": t("Name", "Name"),
                        "api_key": t("API key", "API-Schlüssel"),
                        "key_validity_days": t("Validity chosen for the key (days)", "Beim Erstellen gewählte Gültigkeit (Tage)"),
                    },
                },
                "reauth_confirm": {
                    "title": t("New API key", "Neuer API-Schlüssel"),
                    "description": t("The key for {account} no longer works (expected to expire on {expires}). Create a new key in the same Garmin account in [Garmin Connect]({key_url}) and enter it.",
                                     "Der Schlüssel für {account} funktioniert nicht mehr (erwartetes Ablaufdatum: {expires}). Erzeuge im selben Garmin-Konto in [Garmin Connect]({key_url}) einen neuen Schlüssel und gib ihn ein."),
                    "data": {"api_key": t("API key", "API-Schlüssel"), "key_validity_days": t("Validity (days)", "Gültigkeit (Tage)")},
                },
                "reconfigure": {
                    "title": t("Replace API key", "API-Schlüssel ersetzen"),
                    "description": t("Enter a new key for {account} (expected to expire on {expires}). Create it in the same Garmin account in [Garmin Connect]({key_url}).",
                                     "Gib einen neuen Schlüssel für {account} ein (erwartetes Ablaufdatum: {expires}). Erzeuge ihn im selben Garmin-Konto in [Garmin Connect]({key_url})."),
                    "data": {"api_key": t("API key", "API-Schlüssel"), "key_validity_days": t("Validity (days)", "Gültigkeit (Tage)")},
                },
            },
            "error": {
                "invalid_auth": t("The key was rejected by Garmin.", "Garmin hat den Schlüssel abgelehnt."),
                "cannot_connect": t("Could not reach Garmin.", "Garmin ist nicht erreichbar."),
                "unknown": t("Unexpected error, see the log.", "Unerwarteter Fehler, siehe Log."),
                "name_required": t("Please enter a name.", "Bitte gib einen Namen ein."),
                "account_id_missing": t("Garmin did not return an account ID, so the account cannot be identified.",
                                        "Garmin hat keine Konto-ID geliefert. Das Konto kann nicht eindeutig erkannt werden."),
            },
            "abort": {
                "already_configured": t("This account is already set up.", "Dieses Konto ist bereits eingerichtet."),
                "reauth_successful": t("The key was updated.", "Der Schlüssel wurde aktualisiert."),
                "reconfigure_successful": t("The key was updated.", "Der Schlüssel wurde aktualisiert."),
                "wrong_account": t("This key belongs to a different Garmin account than this entry. Create the key in the same Garmin account.",
                                   "Dieser Schlüssel gehört zu einem anderen Garmin-Konto als der Eintrag. Erzeuge den Schlüssel im selben Garmin-Konto."),
            },
        },
        "options": {
            "step": {
                "init": {
                    "title": t("Options", "Optionen"),
                    "data": {
                        "daily_interval_minutes": t("Update interval for daily values (minutes)", "Abrufintervall Tageswerte (Minuten)"),
                        "intraday_attributes": t("Add intraday series as attributes (large)", "Tagesverläufe als Attribute anhängen (groß)"),
                        "hourly_statistics": t("Write hourly statistics (heart rate, Body Battery, SpO2)", "Stundenstatistik schreiben (Puls, Body Battery, SpO2)"),
                        "sync_stale_hours": t("Warn when the watch has not synced for (hours)", "Warnen, wenn die Uhr länger nicht synchronisiert wurde als (Stunden)"),
                    },
                }
            }
        },
        "selector": {
            "key_validity": {"options": {d: t(f"{d} days", f"{d} Tage") for d in ("30", "90", "180", "365")}},
            "endpoint": {"options": {k: v[i] for k, v in ENDPOINT_NAMES.items()}},
        },
        "entity": {
            "sensor": {k: ({"name": N[k][i]} | ({"state": {v: names[i] for v, names in LABELS[LABEL_OF[k]].items()}} if k in LABEL_OF else {})) for k in keys},
            "binary_sensor": {"sync_stale": {"name": t("Watch sync overdue", "Uhr-Synchronisation überfällig")}},
            "calendar": {"activities": {"name": t("Activities", "Aktivitäten")}},
            "event": {"activity": {"name": t("Activity", "Aktivität"),
                                   "state_attributes": {"event_type": {"state": {"activity_finished": t("New activity", "Neue Aktivität")}}}}},
        },
        "issues": {
            "key_expiring": {
                "title": t("Garmin API key for {account} expires soon", "Garmin-Schlüssel für {account} läuft bald ab"),
                "description": t(
                    "The API key for {account} is expected to expire on {expires} ({days_left} days left). Garmin does not report the expiry date; it is calculated from your entry during setup. Create a new key in Garmin Connect in time and enter it via Reconfigure.",
                    "Der API-Schlüssel für {account} läuft voraussichtlich am {expires} ab (noch {days_left} Tage). Garmin meldet das Ablaufdatum nicht; es wird aus deiner Angabe bei der Einrichtung berechnet. Erzeuge rechtzeitig einen neuen Schlüssel in Garmin Connect und trage ihn über „Neu konfigurieren“ ein.",
                ),
            },
            "key_expired": {
                "title": t("Garmin API key for {account} has expired", "Garmin-Schlüssel für {account} abgelaufen"),
                "description": t(
                    "According to your entry the API key for {account} expired on {expires}. Create a new key in Garmin Connect and enter it via Reconfigure.",
                    "Der API-Schlüssel für {account} ist laut deiner Angabe seit {expires} abgelaufen. Erzeuge einen neuen Schlüssel in Garmin Connect und trage ihn über „Neu konfigurieren“ ein.",
                ),
            },
        },
        "services": {
            "fetch": {"name": t("Fetch data", "Daten abrufen"),
                      "description": t("Fetch any Garmin endpoint for a day or range and return the raw result.",
                                       "Ruft einen beliebigen Garmin-Endpunkt für einen Tag oder Zeitraum ab und liefert das Rohergebnis."),
                      "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Garmin account. May be left out only if exactly one account is set up.", "Garmin-Konto. Darf nur weggelassen werden, wenn genau ein Konto eingerichtet ist.")},
                                 "endpoint": {"name": t("Endpoint", "Endpunkt"), "description": t("Short name of the endpoint.", "Kurzname des Endpunkts.")},
                                 "date": {"name": t("Date", "Datum"), "description": t("For single-day endpoints (default today).", "Für Endpunkte mit einem Tag (Standard: heute).")},
                                 "start_date": {"name": t("Start date", "Startdatum"), "description": t("For range endpoints.", "Für Zeitraum-Endpunkte.")},
                                 "end_date": {"name": t("End date", "Enddatum"), "description": t("For range endpoints.", "Für Zeitraum-Endpunkte.")},
                                 "activity_id": {"name": t("Activity ID", "Aktivitäts-ID"), "description": t("For activity endpoints.", "Für Aktivitäts-Endpunkte.")},
                                 "filters": {"name": t("Filters", "Filter"), "description": t("Activity filters as a mapping, e.g. activity_type: running, min_distance: 10000, favorite: false.", "Aktivitätsfilter als Mapping, z. B. activity_type: running, min_distance: 10000, favorite: false.")},
                                 "limit": {"name": t("Limit", "Limit"), "description": t("Maximum number of activities.", "Maximale Anzahl Aktivitäten.")}}},
            "search_activities": {"name": t("Search activities", "Aktivitäten suchen"),
                                  "description": t("Search activities with filters; pages automatically.", "Sucht Aktivitäten mit Filtern; blättert automatisch."),
                                  "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Garmin account. May be left out only if exactly one account is set up.", "Garmin-Konto. Darf nur weggelassen werden, wenn genau ein Konto eingerichtet ist.")},
                                             "filters": {"name": t("Filters", "Filter"), "description": t("Filters as a mapping, for example activity_type, min_distance, start_date, favorite.", "Filter als Mapping, zum Beispiel activity_type, min_distance, start_date, favorite.")},
                                             "limit": {"name": t("Limit", "Limit"), "description": t("Maximum number of activities.", "Maximale Anzahl Aktivitäten.")}}},
            "download_activity": {"name": t("Download activity file", "Aktivitätsdatei herunterladen"),
                                  "description": t("Saves the original activity files (ZIP) to an allowed folder.", "Speichert die Original-Aktivitätsdateien (ZIP) in einem erlaubten Ordner."),
                                  "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Garmin account. May be left out only if exactly one account is set up.", "Garmin-Konto. Darf nur weggelassen werden, wenn genau ein Konto eingerichtet ist.")},
                                             "activity_id": {"name": t("Activity ID", "Aktivitäts-ID"), "description": t("ID of the activity.", "ID der Aktivität.")},
                                             "path": {"name": t("Target file", "Zieldatei"), "description": t("Target .zip file or a folder. Default: folder garmin_personal in the media folder, file activity_ID.zip. The folder must be allowed in allowlist_external_dirs (media folders are).", "Ziel-.zip-Datei oder Ordner. Standard: Ordner garmin_personal im Medienordner, Datei activity_ID.zip. Der Ordner muss in allowlist_external_dirs erlaubt sein (Medienordner sind es).")}}},
            "backfill_statistics": {"name": t("Import daily values as statistics", "Tageswerte als Statistik importieren"),
                                    "description": t("Writes daily values (activity, sleep, HRV, weight) into long-term statistics (external, one value per day). Safe to repeat. Runs in 31-day windows; the response says whether it completed (complete, last_completed_day, error) and how many days and rows were written (days_imported, statistic_series, statistic_rows).",
                                                     "Schreibt Tageswerte (Aktivität, Schlaf, HRV, Gewicht) in die Langzeitstatistik (extern, ein Wert pro Tag). Kann gefahrlos wiederholt werden. Läuft in 31-Tage-Fenstern; die Antwort sagt, ob alles fertig wurde (complete, last_completed_day, error) und wie viele Tage und Zeilen geschrieben wurden (days_imported, statistic_series, statistic_rows)."),
                                    "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Garmin account. May be left out only if exactly one account is set up.", "Garmin-Konto. Darf nur weggelassen werden, wenn genau ein Konto eingerichtet ist.")},
                                               "start_date": {"name": t("Start date", "Startdatum"), "description": t("Default: days back from the end date.", "Standard: Tage rückwärts ab Enddatum.")},
                                               "end_date": {"name": t("End date", "Enddatum"), "description": t("Last day to import. Default: yesterday; today only if given explicitly (an incomplete day).", "Letzter Tag des Imports. Standard: gestern; heute nur, wenn ausdrücklich angegeben (unvollständiger Tag).")},
                                               "days": {"name": t("Days", "Tage"), "description": t("Number of days back from the end date (at most 3650). Used when no start date is given.", "Anzahl Tage rückwärts ab Enddatum (höchstens 3650). Wird ohne Startdatum verwendet.")},
                                               "include_third_party_steps": {"name": t("Steps from other apps", "Schritte aus anderen Apps"), "description": t("Also import steps, distance and floors of days that other apps (e.g. RunGap) wrote into Garmin Connect. Calories and heart rate of those days are never imported.", "Schritte, Distanz und Stockwerke von Tagen mitimportieren, die andere Apps (z. B. RunGap) in Garmin Connect geschrieben haben. Kalorien und Puls dieser Tage werden nie importiert.")}}},
            "backfill_intraday": {"name": t("Import hourly values as statistics", "Stundenwerte als Statistik importieren"),
                                  "description": t("Writes the day curves of heart rate, Body Battery and SpO2 as hourly values (minimum, maximum, mean of each completed hour) into long-term statistics. One request per day and series; a range may span at most 366 days. Safe to repeat: the same hours are overwritten. The response says whether it completed (complete, last_completed_day, error) and how many hours were written per series.",
                                                   "Schreibt die Tagesverläufe von Puls, Body Battery und SpO2 als Stundenwerte (Minimum, Maximum, Mittelwert jeder abgeschlossenen Stunde) in die Langzeitstatistik. Eine Anfrage je Tag und Reihe; ein Zeitraum darf höchstens 366 Tage umfassen. Kann gefahrlos wiederholt werden: dieselben Stunden werden überschrieben. Die Antwort sagt, ob alles fertig wurde (complete, last_completed_day, error) und wie viele Stunden je Reihe geschrieben wurden."),
                                  "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Garmin account. May be left out only if exactly one account is set up.", "Garmin-Konto. Darf nur weggelassen werden, wenn genau ein Konto eingerichtet ist.")},
                                             "start_date": {"name": t("Start date", "Startdatum"), "description": t("Default: days back from the end date.", "Standard: Tage rückwärts ab Enddatum.")},
                                             "end_date": {"name": t("End date", "Enddatum"), "description": t("Last day to import. Default: today (only completed hours are written, never the running hour).", "Letzter Tag des Imports. Standard: heute (es werden nur abgeschlossene Stunden geschrieben, nie die laufende).")},
                                             "days": {"name": t("Days", "Tage"), "description": t("Number of days back from the end date (at most 366, default 7). Used when no start date is given.", "Anzahl Tage rückwärts ab Enddatum (höchstens 366, Standard 7). Wird ohne Startdatum verwendet.")}}},
            "backfill_history": {"name": t("Write history sensors (appending only)", "Verlauf-Sensoren schreiben (nur anhängend)"),
                                 "description": t("Writes the real measuring points of heart rate, Body Battery and SpO2 with their own timestamps as recorded states of the (history) sensors, so the History panel shows them. Appends only: points already written are never written again, overwritten or deleted. Not available yet; see the README.",
                                                  "Schreibt die echten Messpunkte von Puls, Body Battery und SpO2 mit ihren eigenen Zeitstempeln als aufgezeichnete Zustände der (Verlauf-)Sensoren, damit der Bereich Verlauf sie zeigt. Nur anhängend: bereits geschriebene Punkte werden nie erneut geschrieben, überschrieben oder gelöscht. Noch nicht verfügbar; siehe README."),
                                 "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Garmin account. May be left out only if exactly one account is set up.", "Garmin-Konto. Darf nur weggelassen werden, wenn genau ein Konto eingerichtet ist.")},
                                            "start_date": {"name": t("Start date", "Startdatum"), "description": t("Default: days back from the end date.", "Standard: Tage rückwärts ab Enddatum.")},
                                            "end_date": {"name": t("End date", "Enddatum"), "description": t("Last day. Default: today.", "Letzter Tag. Standard: heute.")},
                                            "days": {"name": t("Days", "Tage"), "description": t("Number of days back from the end date (at most 366, default 1).", "Anzahl Tage rückwärts ab Enddatum (höchstens 366, Standard 1).")},
                                            "series": {"name": t("Series", "Reihen"), "description": t("heart_rate, body_battery, spo2 (default: all).", "heart_rate, body_battery, spo2 (Standard: alle).")},
                                            "confirm_rewrite": {"name": t("Confirm without check", "Ohne Prüfung bestätigen"), "description": t("Only if the record of written points is lost and the recorder cannot be checked: write the requested days anyway. This can duplicate states that exist already.", "Nur wenn das Protokoll der geschriebenen Punkte verloren ist und der Recorder nicht geprüft werden kann: die angeforderten Tage trotzdem schreiben. Das kann bereits vorhandene Zustände verdoppeln.")}}},
        },
        "exceptions": {k: {"message": v[i]} for k, v in EXCEPTIONS.items()},
    }
    for (flow, step), fields in DATA_DESCRIPTIONS.items():
        node = out[flow]["step"][step]
        unknown = [f for f in fields if f not in node["data"]]
        if unknown:
            raise GeneratorError(f"data_description for {flow}.{step}: no such field in data: {unknown}")
        node["data_description"] = {f: v[i] for f, v in fields.items()}
    for key, parts in EXTRA_ISSUES.items():
        out["issues"][key] = {name: v[i] for name, v in parts.items()}
    for service, fields in EXTRA_SERVICE_FIELDS.items():
        for field, parts in fields.items():
            out["services"][service]["fields"][field] = {name: v[i] for name, v in parts.items()}
    return out

def icons() -> dict:
    """icons.json: default icon per sensor, from the ICONS table above."""
    sensors = {k: {"default": f"mdi:{icon}"} for k, icon in ICONS.items()}
    return {"entity": {"sensor": sensors, "calendar": {"activities": {"default": "mdi:run"}}}}


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def outputs() -> dict[Path, str]:
    """Every generated file: path -> content."""
    return {
        ROOT / "translations" / "en.json": render(build(0)),
        ROOT / "translations" / "de.json": render(build(1)),
        ROOT / "strings.json": render(build(0)),
        ROOT / "icons.json": render(icons()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="write nothing; fail if a generated file differs")
    args = parser.parse_args(argv)
    try:
        files = outputs()
    except GeneratorError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    if args.check:
        stale = [str(p.relative_to(ROOT)) for p, text in files.items() if not p.exists() or p.read_text() != text]
        if stale:
            print("out of date, run scripts/gen_translations.py:", ", ".join(stale), file=sys.stderr)
            return 1
        print("up to date")
        return 0
    for path, text in files.items():
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
    print("ok", len(keys), "sensor names,", len(ICONS), "icons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
