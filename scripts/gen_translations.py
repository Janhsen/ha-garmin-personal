"""Generate strings.json and translations/{en,de}.json (run from the repo root)."""

import json
import re
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
 "floors_ascended": ("Floors ascended", "Stockwerke hoch"), "floors_descended": ("Floors descended", "Stockwerke runter"),
 "floors_goal": ("Floors goal", "Stockwerke-Ziel"), "highly_active_time": ("Highly active time", "Zeit hochaktiv"),
 "active_time": ("Active time", "Aktive Zeit"), "sedentary_time": ("Sedentary time", "Sitzende Zeit"),
 "heart_rate_resting": ("Resting heart rate", "Ruhepuls"), "heart_rate_resting_7d": ("Resting heart rate (7 days)", "Ruhepuls (7 Tage)"),
 "heart_rate_min": ("Minimum heart rate", "Minimaler Puls"), "heart_rate_max": ("Maximum heart rate", "Maximaler Puls"),
 "stress_average": ("Average stress", "Durchschnittlicher Stress"), "stress_max": ("Maximum stress", "Maximaler Stress"),
 "stress_qualifier": ("Stress level", "Stressstufe"), "stress_rest_time": ("Rest time", "Ruhezeit (Stress)"),
 "stress_low_time": ("Low stress time", "Zeit niedriger Stress"), "stress_medium_time": ("Medium stress time", "Zeit mittlerer Stress"),
 "stress_high_time": ("High stress time", "Zeit hoher Stress"),
 "body_battery": ("Body Battery", "Body Battery"), "body_battery_high": ("Body Battery highest", "Body Battery Höchstwert"),
 "body_battery_low": ("Body Battery lowest", "Body Battery Tiefstwert"), "body_battery_charged": ("Body Battery charged", "Body Battery geladen"),
 "body_battery_drained": ("Body Battery drained", "Body Battery verbraucht"), "body_battery_at_wake": ("Body Battery at wake-up", "Body Battery beim Aufwachen"),
 "body_battery_during_sleep": ("Body Battery during sleep", "Body Battery im Schlaf"),
 "spo2_average": ("Average SpO2", "SpO2 Durchschnitt"), "spo2_lowest": ("Lowest SpO2", "SpO2 Minimum"),
 "spo2_latest": ("Latest SpO2", "SpO2 aktuell"), "spo2_7d": ("SpO2 (7 days)", "SpO2 (7 Tage)"),
 "respiration_waking": ("Respiration (awake)", "Atmung (wach)"), "respiration_latest": ("Respiration (latest)", "Atmung (aktuell)"),
 "hydration": ("Hydration", "Flüssigkeitszufuhr"), "hydration_goal": ("Hydration goal", "Trinkziel"),
 "hydration_sweat_loss": ("Sweat loss", "Schweißverlust"), "last_sync": ("Last sync", "Letzte Synchronisation"),
 "sleep_duration": ("Sleep duration", "Schlafdauer"), "sleep_deep": ("Deep sleep", "Tiefschlaf"),
 "sleep_light": ("Light sleep", "Leichtschlaf"), "sleep_rem": ("REM sleep", "REM-Schlaf"), "sleep_awake": ("Awake time", "Wachzeit"),
 "nap_duration": ("Nap duration", "Nickerchen"), "sleep_score": ("Sleep score", "Schlafwert"),
 "sleep_score_duration": ("Sleep score: duration", "Schlafwert: Dauer"), "sleep_score_stress": ("Sleep score: stress", "Schlafwert: Stress"),
 "sleep_score_restlessness": ("Sleep score: restlessness", "Schlafwert: Unruhe"), "sleep_score_awake_count": ("Sleep score: awakenings", "Schlafwert: Aufwachen"),
 "sleep_score_rem": ("Sleep score: REM", "Schlafwert: REM"), "sleep_score_light": ("Sleep score: light", "Schlafwert: Leichtschlaf"),
 "sleep_score_deep": ("Sleep score: deep", "Schlafwert: Tiefschlaf"), "sleep_start": ("Sleep start", "Schlafbeginn"),
 "sleep_end": ("Sleep end", "Schlafende"), "sleep_awake_count": ("Awakenings", "Aufwachen"),
 "sleep_heart_rate": ("Sleep heart rate", "Puls im Schlaf"), "sleep_stress": ("Sleep stress", "Stress im Schlaf"),
 "sleep_spo2_average": ("Sleep SpO2 average", "SpO2 im Schlaf (Durchschnitt)"), "sleep_spo2_lowest": ("Sleep SpO2 lowest", "SpO2 im Schlaf (Minimum)"),
 "sleep_respiration_average": ("Sleep respiration", "Atmung im Schlaf"), "sleep_need": ("Sleep need", "Schlafbedarf"),
 "sleep_need_next": ("Next sleep need", "Nächster Schlafbedarf"), "sleep_feedback": ("Sleep feedback", "Schlaf-Feedback"),
 "sleep_insight": ("Sleep insight", "Schlaf-Einblick"), "sleep_breathing_disruption": ("Breathing disruption", "Atemaussetzer"),
 "hrv_last_night": ("HRV last night", "HRV letzte Nacht"), "hrv_weekly": ("HRV weekly average", "HRV Wochendurchschnitt"),
 "hrv_5min_high": ("HRV 5 min high", "HRV 5-Min-Höchstwert"), "hrv_status": ("HRV status", "HRV-Status"),
 "hrv_feedback": ("HRV feedback", "HRV-Feedback"),
 "weight": ("Weight", "Gewicht"), "bmi": ("BMI", "BMI"), "body_fat": ("Body fat", "Körperfett"),
 "body_water": ("Body water", "Körperwasser"), "muscle_mass": ("Muscle mass", "Muskelmasse"), "bone_mass": ("Bone mass", "Knochenmasse"),
 "visceral_fat": ("Visceral fat", "Viszerales Fett"), "metabolic_age": ("Metabolic age", "Stoffwechselalter"),
 "fitness_age": ("Fitness age", "Fitnessalter"), "fitness_age_achievable": ("Achievable fitness age", "Erreichbares Fitnessalter"),
 "chronological_age": ("Chronological age", "Kalendarisches Alter"),
 "last_activity": ("Last activity", "Letzte Aktivität"), "last_activity_type": ("Last activity type", "Letzte Aktivität: Typ"),
 "last_activity_start": ("Last activity start", "Letzte Aktivität: Beginn"), "last_activity_distance": ("Last activity distance", "Letzte Aktivität: Distanz"),
 "last_activity_duration": ("Last activity duration", "Letzte Aktivität: Dauer"), "last_activity_calories": ("Last activity calories", "Letzte Aktivität: Kalorien"),
 "last_activity_avg_hr": ("Last activity average HR", "Letzte Aktivität: Ø Puls"), "last_activity_max_hr": ("Last activity max HR", "Letzte Aktivität: Maximalpuls"),
 "last_activity_aerobic_te": ("Last activity aerobic training effect", "Letzte Aktivität: aerober Trainingseffekt"),
 "last_activity_anaerobic_te": ("Last activity anaerobic training effect", "Letzte Aktivität: anaerober Trainingseffekt"),
 "last_activity_load": ("Last activity training load", "Letzte Aktivität: Trainingsbelastung"),
 "last_activity_vo2max": ("Last activity VO2max", "Letzte Aktivität: VO2max"),
 "last_activity_elevation": ("Last activity elevation gain", "Letzte Aktivität: Höhenmeter"),
 "wellness_activities": ("Wellness activities today", "Wellness-Aktivitäten heute"),
 "account": ("Account", "Konto"), "hr_max_used": ("Maximum heart rate (set)", "Maximalpuls (eingestellt)"),
 "hr_resting_used": ("Resting heart rate (set)", "Ruhepuls (eingestellt)"),
 "hr_lactate_threshold": ("Lactate threshold heart rate", "Laktatschwelle Puls"),
 "key_expires": ("API key expires", "API-Schlüssel läuft ab"),
}

keys = re.findall(r'^\s+_d\("([a-z0-9_]+)"', (ROOT / "sensor.py").read_text(), re.M) + ["key_expires"]
missing = [k for k in keys if k not in N]
extra = [k for k in N if k not in keys]
assert not missing and not extra, (missing, extra)

def build(i: int) -> dict:
    de = i == 1
    t = (lambda en, d: d if de else en)
    return {
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
                        "sync_stale_hours": t("Warn when the watch has not synced for (hours)", "Warnen, wenn die Uhr nicht synchronisiert hat seit (Stunden)"),
                    },
                }
            }
        },
        "selector": {
            "key_validity": {"options": {d: t(f"{d} days", f"{d} Tage") for d in ("30", "90", "180", "365")}},
        },
        "entity": {
            "sensor": {k: {"name": N[k][i]} for k in keys},
            "binary_sensor": {"sync_stale": {"name": t("Watch sync overdue", "Uhr-Synchronisation überfällig")}},
            "event": {"activity": {"name": t("Activity", "Aktivität"),
                                   "state_attributes": {"event_type": {"state": {"activity_finished": t("Activity finished", "Aktivität beendet")}}}}},
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
                                 "date": {"name": t("Date", "Datum"), "description": t("For single-day endpoints (default today).", "Für Einzeltag-Endpunkte (Standard heute).")},
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
                                  "description": t("Saves the original activity files (ZIP) to disk.", "Speichert die Original-Aktivitätsdateien (ZIP) auf der Platte."),
                                  "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Only needed with several accounts.", "Nur bei mehreren Konten nötig.")},
                                             "activity_id": {"name": t("Activity ID", "Aktivitäts-ID"), "description": t("ID of the activity.", "ID der Aktivität.")},
                                             "path": {"name": t("Target file", "Zieldatei"), "description": t("Default: garmin_personal folder in the config directory.", "Standard: Ordner garmin_personal im Konfigurationsverzeichnis.")}}},
            "backfill_statistics": {"name": t("Import daily values as statistics", "Tageswerte als Statistik importieren"),
                                    "description": t("Writes daily summary values into long-term statistics (external, one value per day). Safe to repeat.",
                                                     "Schreibt Tageswerte in die Langzeitstatistik (extern, ein Wert pro Tag). Kann gefahrlos wiederholt werden."),
                                    "fields": {"config_entry_id": {"name": t("Account", "Konto"), "description": t("Only needed with several accounts.", "Nur bei mehreren Konten nötig.")},
                                               "start_date": {"name": t("Start date", "Startdatum"), "description": t("Default: days back from the end date.", "Standard: Tage rückwärts ab Enddatum.")},
                                               "end_date": {"name": t("End date", "Enddatum"), "description": t("Default: today.", "Standard: heute.")},
                                               "days": {"name": t("Days", "Tage"), "description": t("Used when no start date is given.", "Wird ohne Startdatum verwendet.")}}},
        },
        "exceptions": {},
    }

out = ROOT / "translations"
out.mkdir(exist_ok=True)
for i, lang in enumerate(("en", "de")):
    (out / f"{lang}.json").write_text(json.dumps(build(i), ensure_ascii=False, indent=2) + "\n")
(ROOT / "strings.json").write_text(json.dumps(build(0), ensure_ascii=False, indent=2) + "\n")
print("ok", len(keys))
