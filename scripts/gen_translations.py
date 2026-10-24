"""Generate strings.json and translations/{en,de}.json (run from the repo root)."""

import argparse
import ast
import importlib.util
import json
import re
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
}

# ---------------------------------------------------------------------------
# Data that is added to by hand. The generator only assembles; nothing here is derived from code.
# Format: key -> (English, German). Placeholders such as {error} must appear in both languages.

# exceptions.<key>.message, raised as HomeAssistantError(translation_domain=DOMAIN, translation_key=<key>).
EXCEPTIONS: dict[str, tuple[str, str]] = {}

# <flow>.step.<step>.data_description.<field>; every field must also exist in the step's "data".
DATA_DESCRIPTIONS: dict[tuple[str, str], dict[str, tuple[str, str]]] = {
    ("config", "user"): {
        "name": ("Name of this account in Home Assistant, for example the person's first name.",
                 "Name dieses Kontos in Home Assistant, zum Beispiel der Vorname der Person."),
        "api_key": ("The key from Garmin Connect. It is stored only in Home Assistant.",
                    "Der Schlüssel aus Garmin Connect. Er wird nur in Home Assistant gespeichert."),
        "key_validity_days": ("The validity you chose at Garmin when creating the key. Garmin does not reveal the expiry date, "
                              "so the integration calculates it from this value; it is an estimate and only used for the reminder.",
                              "Die Gültigkeit, die du bei Garmin beim Erstellen des Schlüssels gewählt hast. Garmin verrät das Ablaufdatum nicht; "
                              "die Integration berechnet es daraus. Es ist eine Schätzung und dient nur der Erinnerung."),
    },
    ("config", "reauth_confirm"): {
        "key_validity_days": ("The validity you chose at Garmin for the new key. The expiry date is calculated from it (estimate).",
                              "Die Gültigkeit, die du bei Garmin für den neuen Schlüssel gewählt hast. Daraus wird das Ablaufdatum berechnet (Schätzung)."),
    },
    ("config", "reconfigure"): {
        "key_validity_days": ("The validity you chose at Garmin for the new key. The expiry date is calculated from it (estimate).",
                              "Die Gültigkeit, die du bei Garmin für den neuen Schlüssel gewählt hast. Daraus wird das Ablaufdatum berechnet (Schätzung)."),
    },
    ("options", "init"): {
        "daily_interval_minutes": ("How often the daily summary is requested. A new watch sync triggers the other requests.",
                                   "Wie oft die Tageszusammenfassung abgefragt wird. Ein neuer Uhr-Sync löst die übrigen Abfragen aus."),
        "intraday_attributes": ("Adds heart rate, Body Battery and SpO2 series to the sensors as attributes. This makes the state data "
                                "large and requests extra data from Garmin.",
                                "Hängt Puls-, Body-Battery- und SpO2-Verläufe als Attribute an die Sensoren. Das macht die Zustandsdaten "
                                "groß und ruft zusätzliche Daten bei Garmin ab."),
        "sync_stale_hours": ("The binary sensor reports a problem when the last watch sync is older than this.",
                             "Der Binärsensor meldet ein Problem, wenn der letzte Uhr-Sync länger her ist."),
    },
}

# Further repair issues: key -> {"title": (en, de), "description": (en, de)} (key_expiring is built in below).
EXTRA_ISSUES: dict[str, dict[str, tuple[str, str]]] = {}

# Extra service fields: service -> field -> {"name": (en, de), "description": (en, de)}; added to the built-in fields.
EXTRA_SERVICE_FIELDS: dict[str, dict[str, dict[str, tuple[str, str]]]] = {}


class GeneratorError(Exception):
    """Raised with a message that says what to fix; the command line prints it and exits with 1."""


def parse_descriptors(source: str) -> list[tuple[str, str | None, str | None]]:
    """(key, labels, icon) of every ``_d("key", ...)`` call in sensor.py, read from the syntax tree.

    The tree does not depend on line breaks or on Home Assistant, and an argument that is not a
    plain string constant is an error instead of being skipped silently.
    """
    out: list[tuple[str, str | None, str | None]] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_d"):
            continue
        if not node.args or not (isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            raise GeneratorError(f"sensor.py line {node.lineno}: first argument of _d() must be a string literal")
        key = node.args[0].value
        found: dict[str, str | None] = {"labels": None, "icon": None}
        for kw in node.keywords:
            if kw.arg in found:
                if not (isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)):
                    raise GeneratorError(f"sensor.py line {node.lineno}: {kw.arg}= of sensor {key!r} must be a string literal")
                found[kw.arg] = kw.value.value
        out.append((key, found["labels"], found["icon"]))
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
keys = [k for k, _, _ in _DESCRIPTORS] + ["key_expires"]
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
                        "Create a key at connect.garmin.com/app/settings/personalApiToken and paste it here. Garmin shows it only once.",
                        "Erstelle unter connect.garmin.com/app/settings/personalApiToken einen Schlüssel und füge ihn hier ein. Garmin zeigt ihn nur einmal an.",
                    ),
                    "data": {
                        "name": t("Name", "Name"),
                        "api_key": t("API key", "API-Schlüssel"),
                        "key_validity_days": t("Validity chosen for the key (days)", "Beim Erstellen gewählte Gültigkeit (Tage)"),
                    },
                },
                "reauth_confirm": {
                    "title": t("New API key", "Neuer API-Schlüssel"),
                    "description": t("The key for {account} no longer works. Create a new one and enter it.",
                                     "Der Schlüssel für {account} funktioniert nicht mehr. Erstelle einen neuen und gib ihn ein."),
                    "data": {"api_key": t("API key", "API-Schlüssel"), "key_validity_days": t("Validity (days)", "Gültigkeit (Tage)")},
                },
                "reconfigure": {
                    "title": t("Replace API key", "API-Schlüssel ersetzen"),
                    "description": t("Enter a new key for {account}.", "Gib einen neuen Schlüssel für {account} ein."),
                    "data": {"api_key": t("API key", "API-Schlüssel"), "key_validity_days": t("Validity (days)", "Gültigkeit (Tage)")},
                },
            },
            "error": {
                "invalid_auth": t("The key was rejected by Garmin.", "Garmin hat den Schlüssel abgelehnt."),
                "cannot_connect": t("Could not reach Garmin.", "Garmin ist nicht erreichbar."),
                "unknown": t("Unexpected error, see the log.", "Unerwarteter Fehler, siehe Log."),
            },
            "abort": {
                "already_configured": t("This account is already set up.", "Dieses Konto ist bereits eingerichtet."),
                "reauth_successful": t("The key was updated.", "Der Schlüssel wurde aktualisiert."),
                "reconfigure_successful": t("The key was updated.", "Der Schlüssel wurde aktualisiert."),
                "wrong_account": t("This key belongs to a different Garmin account.", "Dieser Schlüssel gehört zu einem anderen Garmin-Konto."),
            },
        },
        "options": {
            "step": {
                "init": {
                    "title": t("Options", "Optionen"),
                    "data": {
                        "daily_interval_minutes": t("Update interval for daily values (minutes)", "Abrufintervall Tageswerte (Minuten)"),
                        "intraday_attributes": t("Add intraday series as attributes (large)", "Tagesverläufe als Attribute anhängen (groß)"),
                        "sync_stale_hours": t("Warn when the watch has not synced for (hours)", "Warnen, wenn die Uhr länger nicht synchronisiert wurde als (Stunden)"),
                    },
                }
            }
        },
        "selector": {
            "key_validity": {"options": {d: t(f"{d} days", f"{d} Tage") for d in ("30", "90", "180", "365")}},
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
                "title": t("Garmin API key expires soon", "Garmin-API-Schlüssel läuft bald ab"),
                "description": t(
                    "The Personal API key for {account} expires on {expires}. Create a new key in Garmin Connect and use Reconfigure on the integration.",
                    "Der Personal-API-Schlüssel für {account} läuft am {expires} ab. Erstelle in Garmin Connect einen neuen und nutze am Eintrag „Neu konfigurieren“.",
                ),
            }
        },
        "services": {
            "fetch": {"name": t("Fetch data", "Daten abrufen"),
                      "description": t("Fetch any Garmin endpoint for a day or range and return the raw result.",
                                       "Ruft einen beliebigen Garmin-Endpunkt für einen Tag oder Zeitraum ab und liefert das Rohergebnis."),
                      "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Only needed with several accounts.", "Nur bei mehreren Konten nötig.")},
                                 "endpoint": {"name": t("Endpoint", "Endpunkt"), "description": t("Short name of the endpoint.", "Kurzname des Endpunkts.")},
                                 "date": {"name": t("Date", "Datum"), "description": t("For single-day endpoints (default today).", "Für Endpunkte mit einem Tag (Standard: heute).")},
                                 "start_date": {"name": t("Start date", "Startdatum"), "description": t("For range endpoints.", "Für Zeitraum-Endpunkte.")},
                                 "end_date": {"name": t("End date", "Enddatum"), "description": t("For range endpoints.", "Für Zeitraum-Endpunkte.")},
                                 "activity_id": {"name": t("Activity ID", "Aktivitäts-ID"), "description": t("For activity endpoints.", "Für Aktivitäts-Endpunkte.")},
                                 "filters": {"name": t("Filters", "Filter"), "description": t("Activity filters, e.g. activity_type.", "Aktivitätsfilter, z. B. activity_type.")},
                                 "limit": {"name": t("Limit", "Limit"), "description": t("Maximum number of activities.", "Maximale Anzahl Aktivitäten.")}}},
            "search_activities": {"name": t("Search activities", "Aktivitäten suchen"),
                                  "description": t("Search activities with filters; pages automatically.", "Sucht Aktivitäten mit Filtern; blättert automatisch."),
                                  "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Only needed with several accounts.", "Nur bei mehreren Konten nötig.")},
                                             "filters": {"name": t("Filters", "Filter"), "description": t("For example activity_type, min_distance, start_date.", "Zum Beispiel activity_type, min_distance, start_date.")},
                                             "limit": {"name": t("Limit", "Limit"), "description": t("Maximum number of activities.", "Maximale Anzahl Aktivitäten.")}}},
            "download_activity": {"name": t("Download activity file", "Aktivitätsdatei herunterladen"),
                                  "description": t("Saves the original activity files (ZIP) to disk.", "Speichert die Original-Aktivitätsdateien (ZIP) im Dateisystem."),
                                  "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Only needed with several accounts.", "Nur bei mehreren Konten nötig.")},
                                             "activity_id": {"name": t("Activity ID", "Aktivitäts-ID"), "description": t("ID of the activity.", "ID der Aktivität.")},
                                             "path": {"name": t("Target file", "Zieldatei"), "description": t("Default: garmin_personal folder in the config directory.", "Standard: Ordner garmin_personal im Konfigurationsverzeichnis.")}}},
            "backfill_statistics": {"name": t("Import daily values as statistics", "Tageswerte als Statistik importieren"),
                                    "description": t("Writes daily values (activity, sleep, HRV, weight) into long-term statistics (external, one value per day). Safe to repeat.",
                                                     "Schreibt Tageswerte (Aktivität, Schlaf, HRV, Gewicht) in die Langzeitstatistik (extern, ein Wert pro Tag). Kann gefahrlos wiederholt werden."),
                                    "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Only needed with several accounts.", "Nur bei mehreren Konten nötig.")},
                                               "start_date": {"name": t("Start date", "Startdatum"), "description": t("Default: days back from the end date.", "Standard: Tage rückwärts ab Enddatum.")},
                                               "end_date": {"name": t("End date", "Enddatum"), "description": t("Default: today.", "Standard: heute.")},
                                               "days": {"name": t("Days", "Tage"), "description": t("Used when no start date is given.", "Wird ohne Startdatum verwendet.")},
                                               "include_third_party_steps": {"name": t("Steps from other apps", "Schritte aus anderen Apps"), "description": t("Also import steps, distance and floors of days that other apps (e.g. RunGap) wrote into Garmin Connect. Calories and heart rate of those days are never imported.", "Schritte, Distanz und Stockwerke von Tagen mitimportieren, die andere Apps (z. B. RunGap) in Garmin Connect geschrieben haben. Kalorien und Puls dieser Tage werden nie importiert.")}}},
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
    """icons.json: default icon per sensor, taken from the descriptors (icon="mdi:...")."""
    sensors = {k: {"default": icon} for k, _, icon in _DESCRIPTORS if icon}
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
    print("ok", len(keys), "sensor names,", sum(1 for _, _, i in _DESCRIPTORS if i), "icons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
