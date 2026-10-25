"""Key paths of a Garmin API response (names only, never values), for spotting new or removed fields.

python3 -I scripts/api_fields.py FILE [FILE ...]   prints the sorted key paths of the JSON data
python3 -I scripts/api_fields.py --diff BASELINE FILE [FILE ...]   prints added (+) and removed (-) paths

FILE is either a raw JSON response or a Home Assistant service response with ``service_response.data``.
List items are folded into ``[]``. Only key names are read, so the baseline holds no personal data.

From Garmin's specification (``docs/garmin-personal-swagger.json``, no network needed):

python3 -I scripts/api_fields.py --spec [NAME]       key paths the specification lists, per endpoint (``fetch`` name)
python3 -I scripts/api_fields.py --write-spec        regenerate docs/api-fields/spec-paths.json and spec-unused.json
python3 -I scripts/api_fields.py --check-spec        fail if those two files are out of date (also tests/test_spec_fields.py)
python3 -I scripts/api_fields.py --diff-spec OLD NEW   what a new specification file adds or removes (paths per endpoint)
python3 -I scripts/api_fields.py --table en|de       the endpoint table of the README
python3 -I scripts/api_fields.py --write-readme / --check-readme   keep that table in README.md and README.de.md current

The specification lists more than Garmin sends and sometimes less (for example ``sleepScores``): keep it apart from
the baselines made from real responses.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT / "docs" / "garmin-personal-swagger.json"
SPEC_PATHS_FILE = ROOT / "docs" / "api-fields" / "spec-paths.json"
SPEC_UNUSED_FILE = ROOT / "docs" / "api-fields" / "spec-unused.json"
PACKAGE = ROOT / "custom_components" / "garmin_personal"


def paths(node, prefix=""):
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{prefix}.{key}" if prefix else key
            found.add(here)
            found |= paths(value, here)
    elif isinstance(node, list):
        for item in node:
            found |= paths(item, prefix + "[]")
    return found


def load(file):
    data = json.load(open(file))
    if isinstance(data, dict) and "service_response" in data:
        data = data["service_response"].get("data", data["service_response"])
    return data


# ---------------------------------------------------------------------------
# Garmin's specification (OpenAPI file in docs/)
# ---------------------------------------------------------------------------

DOWNLOAD = "download_activity"  # the 26th path: a service of its own, not part of ``fetch``

# Each row: spec path, name (``fetch`` endpoint or service), largest range per request, where that limit comes
# from, entities and attributes, refresh. Texts are (English, German). The limits are checked against
# const.py and the specification by tests/test_spec_fields.py.
T = lambda en, de: (en, de)  # noqa: E731
ENDPOINTS: list[tuple] = [
    ("/activity-service/activity/{activityId}", "activity", None, None,
     T("service only", "nur Dienst"), T("on call", "bei Aufruf")),
    ("/activity-service/activity/{activityId}/workouts", "activity_workouts", None, None,
     T("service only", "nur Dienst"), T("on call", "bei Aufruf")),
    ("/activitylist-service/activities/search/activities", "activities", "about 45 per page", "observed",
     T("*Last activity* sensors and their attributes, event *Activity*, calendar",
       "Sensoren *Letzte Aktivität* samt Attributen, Ereignis *Aktivität*, Kalender"),
     T("new sync, otherwise 1 h", "neuer Sync, sonst 1 h")),
    ("/biometric-service/heartRateZones/v2", "hr_zones", None, None,
     T("maximum, resting and lactate threshold heart rate; zone floors as attributes of *Maximum heart rate (set)*",
       "Max-, Ruhe- und Laktatschwellenpuls; Zonen-Untergrenzen als Attribute von *Maximaler Puls (eingestellt)*"),
     T("24 h", "24 h")),
    ("/download-service/files/activity/{activityId}", DOWNLOAD, None, None,
     T("service `download_activity` (ZIP with the FIT file)", "Dienst `download_activity` (ZIP mit der FIT-Datei)"),
     T("on call", "bei Aufruf")),
    ("/fitnessage-service/fitnessage/v2/{calendarDate}", "fitness_age", "28 days look-back", "spec",
     T("fitness age, achievable and chronological age; attributes `previous_fitness_age`, `components`",
       "Fitnessalter, erreichbares und tatsächliches Alter; Attribute `previous_fitness_age`, `components`"),
     T("new sync, otherwise 1 h", "neuer Sync, sonst 1 h")),
    ("/goal-service/goal/user/effective/weightgoal/{startDate}/{endDate}", "weight_goals", None, None,
     T("service only", "nur Dienst"), T("on call", "bei Aufruf")),
    ("/hrv-service/hrv/{calendarDate}", "hrv", "1 day", "spec",
     T("*HRV (history)* (nightly readings)", "*HRV (Verlauf)* (nächtliche Einzelwerte)"),
     T("new sync, with the history option", "neuer Sync, mit der Verlauf-Option")),
    ("/hrv-service/hrv/daily/{fromDate}/{toDate}", "hrv_summaries", "365 days", "observed",
     T("HRV last night, week, 5-minute high, status, feedback", "HRV letzte Nacht, Woche, 5-Minuten-Höchstwert, Status, Feedback"),
     T("new sync, otherwise 2 h", "neuer Sync, sonst 2 h")),
    ("/nutrition-service/food/logs/{date}", "nutrition", "1 day", "spec",
     T("no sensor by design (service only)", "bewusst kein Sensor (nur Dienst)"), T("on call", "bei Aufruf")),
    ("/periodichealth-service/menstrualcycle/summary/{calendarDate}", "menstrual_summary", "1 day", "spec",
     T("no sensor by design (service only)", "bewusst kein Sensor (nur Dienst)"), T("on call", "bei Aufruf")),
    ("/periodichealth-service/menstrualcycle/dayview/{calendarDate}", "menstrual_day", "1 day", "spec",
     T("no sensor by design (service only)", "bewusst kein Sensor (nur Dienst)"), T("on call", "bei Aufruf")),
    ("/sleep-service/sleep/dailySleep", "sleep", "1 day", "spec",
     T("sleep sensors (duration, stages, score and sub-scores, start/end, need, alignment, breathing)",
       "Schlafsensoren (Dauer, Phasen, Score und Teilscores, Start/Ende, Bedarf, Ausrichtung, Atmung)"),
     T("new sync, otherwise 2 h", "neuer Sync, sonst 2 h")),
    ("/sleep-service/sleep/dailySleepSummariesByDate", "sleep_summaries", "31 days", "spec",
     T("statistics import `backfill_statistics`", "Statistik-Import `backfill_statistics`"), T("on call", "bei Aufruf")),
    ("/userprofile-service/userprofile/settings", "profile", None, None,
     T("*Account* (attributes: locale, units, time zone, ...)", "*Konto* (Attribute: Sprache, Einheiten, Zeitzone, ...)"),
     T("24 h", "24 h")),
    ("/usersummary-service/stats/hydration/daily/{startDate}/{endDate}", "hydration", "31 days", "spec",
     T("hydration, goal, sweat loss", "Trinkmenge, Ziel, Schweißverlust"),
     T("new sync, otherwise 1 h", "neuer Sync, sonst 1 h")),
    ("/usersummary-service/stats/steps/daily/{startDate}/{endDate}", "steps", "28 days", "spec",
     T("service only: daily totals (no values within a day)", "nur Dienst: Tagessummen (keine Werte innerhalb des Tages)"),
     T("on call", "bei Aufruf")),
    ("/usersummary-service/stats/stress/daily/{startDate}/{endDate}", "stress", "28 days", "spec",
     T("service only: daily values (no stress curve)", "nur Dienst: Tageswerte (keine Stresskurve)"),
     T("on call", "bei Aufruf")),
    ("/usersummary-service/usersummary/daily", "daily_summary", "1 day", "spec",
     T("daily sensors: steps, distance, calories, intensity minutes, floors, heart rate, stress, Body Battery, "
       "respiration, heart rate alerts, last sync",
       "Tagessensoren: Schritte, Distanz, Kalorien, Intensitätsminuten, Stockwerke, Puls, Stress, Body Battery, "
       "Atmung, Pulsalarme, letzte Synchronisation"),
     T("every 5 min (sync check)", "alle 5 min (Sync-Prüfung)")),
    ("/usersummary-service/v2/dailysummaries", "daily_summaries", "31 days (spec: 1 year)", "code",
     T("statistics import `backfill_statistics`", "Statistik-Import `backfill_statistics`"), T("on call", "bei Aufruf")),
    ("/weight-service/weight/all/{startDate}/{endDate}", "weights_all", None, None,
     T("service only; Garmin currently answers HTTP 400", "nur Dienst; Garmin antwortet derzeit mit HTTP 400"),
     T("on call", "bei Aufruf")),
    ("/weight-service/weight/range/{startDate}/{endDate}", "weight_range", "360 days", "observed",
     T("weight, BMI, body fat/water, muscle/bone mass, visceral fat, metabolic age",
       "Gewicht, BMI, Körperfett/-wasser, Muskel-/Knochenmasse, Viszeralfett, Stoffwechselalter"),
     T("new sync, otherwise 1 h (90 days)", "neuer Sync, sonst 1 h (90 Tage)")),
    ("/wellness-service/wellness/bodyBattery/reports/daily", "body_battery", "31 days", "spec",
     T("Body Battery series (attribute, hourly statistics, *Body Battery (history)*)",
       "Body-Battery-Verlauf (Attribut, Stundenstatistik, *Body Battery (Verlauf)*)"),
     T("new sync, with an intraday, hourly or history option", "neuer Sync, mit Intraday-, Stunden- oder Verlauf-Option")),
    ("/wellness-service/wellness/daily/spo2acclimation/{calendarDate}", "spo2", "1 day", "spec",
     T("SpO2 average, lowest, latest, 7 days; hourly SpO2 series", "SpO2 Mittel, Tiefstwert, aktuell, 7 Tage; SpO2-Stundenreihe"),
     T("new sync, otherwise 1 h", "neuer Sync, sonst 1 h")),
    ("/wellness-service/wellness/dailyHeartRate", "heart_rate", "1 day", "spec",
     T("heart rate series (attribute, hourly statistics, *Heart rate (history)*); alert thresholds as attributes of "
       "*Heart rate alerts*",
       "Pulsverlauf (Attribut, Stundenstatistik, *Puls (Verlauf)*); Alarmschwellen als Attribute von *Pulsalarme*"),
     T("new sync, with an intraday, hourly or history option", "neuer Sync, mit Intraday-, Stunden- oder Verlauf-Option")),
    ("/wellnessactivity-service/activity/summary/range/{fromDate}/{untilDate}", "wellness_activities", "31 days", "observed",
     T("*Wellness activities today* (count)", "*Wellness-Aktivitäten heute* (Anzahl)"),
     T("new sync, otherwise 1 h", "neuer Sync, sonst 1 h")),
]
LIMIT_DE = {
    "about 45 per page": "etwa 45 je Seite",
    "28 days look-back": "28 Tage Rückschau",
    "1 day": "1 Tag",
    "365 days": "365 Tage",
    "31 days": "31 Tage",
    "28 days": "28 Tage",
    "360 days": "360 Tage",
    "31 days (spec: 1 year)": "31 Tage (Spec: 1 Jahr)",
}
SOURCE_DE = {"spec": "Spec", "observed": "beobachtet", "code": "Code"}
SOURCE_EN = {"spec": "spec", "observed": "observed", "code": "code"}
TABLE_START, TABLE_END = "<!-- endpoints:start (generated by scripts/api_fields.py --write-readme) -->", "<!-- endpoints:end -->"

# Fields that the code reads through a name built at run time (an f-string), so a plain text search misses them.
DYNAMIC_USED = {f"zone{n}Floor" for n in range(1, 6)}


def load_spec(file=SPEC_FILE):
    return json.loads(Path(file).read_text())


def _resolve(spec, node):
    """Follow ``$ref`` and merge ``allOf``; returns a schema dict without those."""
    seen = 0
    while isinstance(node, dict) and ("$ref" in node or "allOf" in node) and seen < 20:
        seen += 1
        if "$ref" in node:
            node = spec["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]]
        else:
            merged = {k: v for k, v in node.items() if k != "allOf"}
            props = dict(merged.get("properties") or {})
            for part in node["allOf"]:
                part = _resolve(spec, part)
                props.update(part.get("properties") or {})
                for key in ("items", "additionalProperties"):
                    if key in part:
                        merged.setdefault(key, part[key])
            merged["properties"] = props
            node = merged
    return node if isinstance(node, dict) else {}


def schema_paths(spec, node, prefix="", trail=()):
    """Key paths of a schema in the notation of ``paths()`` (list items as ``[]``, maps as ``*``)."""
    found = set()
    ref = node.get("$ref") if isinstance(node, dict) else None
    if ref is not None:
        if ref in trail:  # a schema that contains itself
            return found
        trail = (*trail, ref)
    node = _resolve(spec, node)
    for key, value in (node.get("properties") or {}).items():
        here = f"{prefix}.{key}" if prefix else key
        found.add(here)
        found |= schema_paths(spec, value, here, trail)
    if isinstance(node.get("items"), dict):
        found |= schema_paths(spec, node["items"], prefix + "[]", trail)
    if isinstance(node.get("additionalProperties"), dict):
        here = f"{prefix}.*" if prefix else "*"
        found.add(here)
        found |= schema_paths(spec, node["additionalProperties"], here, trail)
    return found


def response_schema(operation):
    content = ((operation.get("responses") or {}).get("200") or {}).get("content") or {}
    return (content.get("application/json") or {}).get("schema")


def spec_paths_by_endpoint(spec):
    """``{name: sorted key paths}`` for every path of the specification that is in ``ENDPOINTS``."""
    names = {row[0]: row[1] for row in ENDPOINTS}
    out = {}
    for path, methods in spec["paths"].items():
        schema = response_schema(methods.get("get") or {})
        if path in names and schema is not None:
            out[names[path]] = sorted(schema_paths(spec, schema))
    return dict(sorted(out.items()))


def source_text():
    return "\n".join(f.read_text() for f in sorted(PACKAGE.glob("*.py")))


def unused_fields(by_endpoint, source=None):
    """``endpoint:path`` for every spec field whose name does not appear in the integration's source."""
    source = source if source is not None else source_text()
    out = []
    for name, found in by_endpoint.items():
        for path in found:
            leaf = re.sub(r"\[\]$", "", path.rsplit(".", 1)[-1])
            if leaf != "*" and leaf not in DYNAMIC_USED and leaf not in source:
                out.append(f"{name}:{path}")
    return sorted(out)


def spec_documents(spec=None):
    spec = spec or load_spec()
    by_endpoint = spec_paths_by_endpoint(spec)
    head = {"spec_version": spec.get("info", {}).get("version"), "note": "Key names only, generated by scripts/api_fields.py"}
    return {
        SPEC_PATHS_FILE: {**head, "endpoints": by_endpoint},
        SPEC_UNUSED_FILE: {
            **head,
            "note": "Spec fields whose name appears nowhere in custom_components/garmin_personal: deliberately not "
                    "used (yet). tests/test_spec_fields.py fails when a field is added to this kind of gap, so each "
                    "new field of a newer specification gets looked at once. Regenerate with --write-spec.",
            "unused": unused_fields(by_endpoint),
        },
    }


def render_json(data):
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def diff_spec(old_file, new_file):
    old, new = (spec_paths_by_endpoint(load_spec(f)) for f in (old_file, new_file))
    lines = []
    for name in sorted(set(old) | set(new)):
        a, b = set(old.get(name, ())), set(new.get(name, ()))
        lines += [f"+ {name}:{p}" for p in sorted(b - a)] + [f"- {name}:{p}" for p in sorted(a - b)]
    return lines


def endpoint_table(lang):
    """The README table of all endpoints (``lang`` is ``en`` or ``de``)."""
    i = 0 if lang == "en" else 1
    head = (
        ("Endpoint", "Short name / service", "Largest range per request", "Entities and attributes", "Refresh")
        if lang == "en"
        else ("Endpunkt", "Kurzname / Dienst", "Größter Zeitraum je Anfrage", "Entitäten und Attribute", "Aktualisierung")
    )
    rows = ["| " + " | ".join(head) + " |", "|---|---|---|---|---|"]
    for path, name, limit, source, entities, refresh in ENDPOINTS:
        if limit is None:
            limit_text = "–"
        else:
            tag = (SOURCE_EN if lang == "en" else SOURCE_DE).get(source or "", "")
            limit_text = (limit if lang == "en" else LIMIT_DE[limit]) + (f" ({tag})" if tag else "")
        rows.append(f"| `{path}` | `{name}` | {limit_text} | {entities[i]} | {refresh[i]} |")
    return "\n".join(rows)


def readme_with_table(text, lang):
    start, end = text.find(TABLE_START), text.find(TABLE_END)
    if start < 0 or end < start:
        raise SystemExit("README: endpoint table markers not found")
    return text[: start + len(TABLE_START)] + "\n\n" + endpoint_table(lang) + "\n\n" + text[end:]


README_FILES = {"en": ROOT / "README.md", "de": ROOT / "README.de.md"}


def main(argv):
    if argv and argv[0] == "--spec":
        data = spec_paths_by_endpoint(load_spec())
        names = argv[1:] or list(data)
        print("\n".join(f"{n}:{p}" for n in names for p in data[n]))
        return 0
    if argv and argv[0] in ("--write-spec", "--check-spec"):
        stale = []
        for file, doc in spec_documents().items():
            text = render_json(doc)
            if argv[0] == "--write-spec":
                file.write_text(text)
            elif file == SPEC_UNUSED_FILE:
                # Only a NEW gap counts; a field that the code uses since then may stay in the list.
                known = set(json.loads(file.read_text())["unused"]) if file.exists() else set()
                if set(doc["unused"]) - known:
                    stale.append(file.name)
            elif not file.exists() or file.read_text() != text:
                stale.append(file.name)
        if stale:
            print("out of date, run scripts/api_fields.py --write-spec:", ", ".join(stale), file=sys.stderr)
            return 1
        return 0
    if argv and argv[0] == "--diff-spec":
        print("\n".join(diff_spec(argv[1], argv[2])))
        return 0
    if argv and argv[0] == "--table":
        print(endpoint_table(argv[1] if len(argv) > 1 else "en"))
        return 0
    if argv and argv[0] in ("--write-readme", "--check-readme"):
        stale = []
        for lang, file in README_FILES.items():
            text = file.read_text()
            wanted = readme_with_table(text, lang)
            if argv[0] == "--write-readme":
                file.write_text(wanted)
            elif wanted != text:
                stale.append(file.name)
        if stale:
            print("out of date, run scripts/api_fields.py --write-readme:", ", ".join(stale), file=sys.stderr)
            return 1
        return 0
    if argv and argv[0] == "--diff":
        base = set(json.load(open(argv[1])))
        now = set().union(*(paths(load(f)) for f in argv[2:]))
        for p in sorted(now - base):
            print("+", p)
        for p in sorted(base - now):
            print("-", p)
        return 0
    print("\n".join(sorted(set().union(*(paths(load(f)) for f in argv)))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
