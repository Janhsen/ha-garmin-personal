"""Garmin's specification (docs/garmin-personal-swagger.json) against the integration and the committed field lists.

The test turns red when the specification file changes (new or removed paths and fields), when a path has no
``fetch`` name, or when the specification has a field that the integration neither reads nor lists as
deliberately unused. Run ``python3 -I scripts/api_fields.py --write-spec`` after looking at the difference
(``--diff-spec OLD NEW``). Known gaps are listed in docs/api-fields/spec-unused.json and do not fail the test.
"""

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _load import load  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("api_fields_script", ROOT / "scripts" / "api_fields.py")
af = importlib.util.module_from_spec(_spec)
sys.modules["api_fields_script"] = af
_spec.loader.exec_module(af)

gp = load()
SPEC = af.load_spec()


class Mapping(unittest.TestCase):
    def test_every_spec_path_is_known_and_every_known_path_exists(self):
        spec_paths = set(SPEC["paths"])
        known = {row[0] for row in af.ENDPOINTS}
        self.assertEqual(spec_paths - known, set(), "path in the specification without a row in ENDPOINTS")
        self.assertEqual(known - spec_paths, set(), "ENDPOINTS row whose path is gone from the specification")
        self.assertEqual(len(spec_paths), 26)

    def test_only_reads(self):
        for path, methods in SPEC["paths"].items():
            self.assertEqual(set(methods), {"get"}, path)

    def test_names_are_the_fetch_endpoints_plus_the_download(self):
        names = [row[1] for row in af.ENDPOINTS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(gp.api.ENDPOINT_NAMES) | {af.DOWNLOAD})

    def test_client_requests_the_documented_paths(self):
        source = (ROOT / "custom_components" / "garmin_personal" / "api.py").read_text()
        for path, *_ in af.ENDPOINTS:
            static = path.split("{", 1)[0]
            self.assertIn(static, source, path)

    def test_parameter_names_sent_exist_in_the_specification(self):
        known = {p["name"] for methods in SPEC["paths"].values() for p in methods["get"].get("parameters", [])}
        source = (ROOT / "custom_components" / "garmin_personal" / "api.py").read_text()
        for name in ("chunks", "fullHistoryScan", "includeAll", "generateDefaults", "calendarDate"):
            self.assertIn(name, known)
        sent = set(re.findall(r'\("([A-Za-z]+)", (?:str\(|"true"|[a-z_]+\.isoformat|parse_day)', source))
        self.assertEqual(sent - known, set(), "parameter that the client sends but the specification does not know")


class Limits(unittest.TestCase):
    def test_documented_limits_match_the_code(self):
        const = gp.const
        table = {row[1]: row for row in af.ENDPOINTS}
        expected = {
            "steps": const.MAX_DAYS_STEPS, "stress": const.MAX_DAYS_STRESS, "hydration": const.MAX_DAYS_HYDRATION,
            "body_battery": const.MAX_DAYS_BODY_BATTERY, "sleep_summaries": const.MAX_DAYS_SLEEP,
            "hrv_summaries": const.MAX_DAYS_HRV, "weight_range": const.MAX_DAYS_WEIGHT,
            "wellness_activities": const.MAX_DAYS_WELLNESS_ACTIVITIES,
        }
        for name, days in expected.items():
            self.assertTrue(table[name][2].startswith(f"{days} days"), (name, table[name][2], days))
        self.assertTrue(table["daily_summaries"][2].startswith(f"{const.MAX_DAYS_DAILY_SUMMARIES} days"))

    def test_limits_marked_spec_are_in_the_specification(self):
        said = {"steps": "28 days", "stress": "28 days", "hydration": "31 days", "body_battery": "31 days",
                "sleep_summaries": "31 days", "daily_summaries": "1 year", "fitness_age": "28 days"}
        table = {row[1]: row for row in af.ENDPOINTS}
        for name, words in said.items():
            self.assertIn(words, json.dumps(SPEC["paths"][table[name][0]]), name)
        # every limit that the table calls "spec" is one of those (or a single day)
        for _path, name, limit, source, *_ in af.ENDPOINTS:
            if source == "spec" and limit != "1 day":
                self.assertIn(name, said, name)


class FieldLists(unittest.TestCase):
    def test_committed_spec_paths_are_current(self):
        committed = json.loads(af.SPEC_PATHS_FILE.read_text())
        generated = af.spec_documents(SPEC)[af.SPEC_PATHS_FILE]
        self.assertEqual(committed["spec_version"], generated["spec_version"])
        for name in sorted(set(committed["endpoints"]) | set(generated["endpoints"])):
            old, new = set(committed["endpoints"].get(name, ())), set(generated["endpoints"].get(name, ()))
            self.assertEqual(
                (sorted(new - old), sorted(old - new)), ([], []),
                f"{name}: the specification changed; check it, then run scripts/api_fields.py --write-spec",
            )

    def test_every_spec_field_is_read_or_listed_as_unused(self):
        listed = set(json.loads(af.SPEC_UNUSED_FILE.read_text())["unused"])
        found = set(af.unused_fields(af.spec_paths_by_endpoint(SPEC)))
        self.assertEqual(
            sorted(found - listed), [],
            "new specification fields that the integration does not read: use them or run "
            "scripts/api_fields.py --write-spec to list them as deliberately unused",
        )

    def test_fields_the_integration_reads_are_not_in_the_unused_list(self):
        listed = set(json.loads(af.SPEC_UNUSED_FILE.read_text())["unused"])
        for field in ("daily_summary:abnormalHeartRateAlertsCount", "fitness_age:previousFitnessAge",
                      "activities:[].hrTimeInZone_1", "heart_rate:abnormalHrThresholdValue"):
            self.assertNotIn(field, listed)

    def test_script_check_passes(self):
        self.assertEqual(af.main(["--check-spec"]), 0)


class Generator(unittest.TestCase):
    def test_paths_follow_refs_arrays_and_maps(self):
        spec = {"components": {"schemas": {
            "A": {"type": "object", "properties": {"x": {"type": "integer"}, "b": {"$ref": "#/components/schemas/B"},
                                                   "m": {"type": "object", "additionalProperties": {"$ref": "#/components/schemas/B"}}}},
            "B": {"allOf": [{"type": "object", "properties": {"y": {"type": "string"}, "self": {"$ref": "#/components/schemas/B"}}}],
                  "properties": {"z": {"type": "array", "items": {"$ref": "#/components/schemas/C"}}}},
            "C": {"type": "object", "properties": {"w": {"type": "number"}}},
        }}}
        got = af.schema_paths(spec, {"type": "array", "items": {"$ref": "#/components/schemas/A"}})
        self.assertEqual(got, {
            "[].x", "[].b", "[].b.y", "[].b.self", "[].b.z", "[].b.z[].w",
            "[].m", "[].m.*", "[].m.*.y", "[].m.*.self", "[].m.*.z", "[].m.*.z[].w",
        })

    def test_diff_spec_lists_added_and_removed(self):
        import tempfile

        def spec_with(fields):
            path = next(iter(SPEC["paths"]))
            return {"paths": {path: {"get": {"responses": {"200": {"content": {"application/json": {"schema": {
                "type": "object", "properties": {f: {"type": "integer"} for f in fields}}}}}}}}},
                "components": {"schemas": {}}}

        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp, "old.json"), Path(tmp, "new.json")
            old.write_text(json.dumps(spec_with(["a", "b"])))
            new.write_text(json.dumps(spec_with(["b", "c"])))
            self.assertEqual(af.diff_spec(old, new), ["+ activity:c", "- activity:a"])


class ReadmeTables(unittest.TestCase):
    def test_tables_in_both_readmes_are_current(self):
        for lang, file in af.README_FILES.items():
            text = file.read_text()
            self.assertEqual(af.readme_with_table(text, lang), text, f"{file.name}: run scripts/api_fields.py --write-readme")

    def test_table_covers_every_endpoint_in_both_languages(self):
        for lang in ("en", "de"):
            table = af.endpoint_table(lang)
            self.assertEqual(table.count("\n"), len(af.ENDPOINTS) + 1)
            for path, name, *_ in af.ENDPOINTS:
                self.assertIn(f"`{path}`", table)
                self.assertIn(f"`{name}`", table)

    def test_both_readmes_have_the_same_sections(self):
        def headings(file):
            return [line for line in file.read_text().splitlines() if line.startswith("## ")]

        self.assertEqual(len(headings(ROOT / "README.md")), len(headings(ROOT / "README.de.md")))


if __name__ == "__main__":
    unittest.main()
