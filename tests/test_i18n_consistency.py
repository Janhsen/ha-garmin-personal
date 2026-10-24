"""Translations: generated files match the checked-in ones, en/de agree, nothing dead, nothing missing."""

import contextlib
import importlib
import importlib.util
import io
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stubs  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "custom_components" / "garmin_personal"
STATE_KEY = re.compile(r"^[a-z0-9]+([_-][a-z0-9]+)*$")
PLACEHOLDER = re.compile(r"\{([a-z_0-9]+)\}")


def load_generator():
    spec = importlib.util.spec_from_file_location("gen_translations", REPO / "scripts" / "gen_translations.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def leaves(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from leaves(v, path + (k,))
    else:
        yield path, node


def code_text(*names):
    return "\n".join((PKG / n).read_text() for n in names)


GEN = load_generator()
EN = json.loads((PKG / "translations" / "en.json").read_text())
DE = json.loads((PKG / "translations" / "de.json").read_text())


class GeneratedFiles(unittest.TestCase):
    def test_checked_in_files_equal_generator_output(self):
        for path, text in GEN.outputs().items():
            self.assertEqual(path.read_text(), text, f"{path.name} is out of date: run scripts/gen_translations.py")

    def test_strings_json_equals_english(self):
        self.assertEqual((PKG / "strings.json").read_text(), (PKG / "translations" / "en.json").read_text())

    def test_check_mode_reports_up_to_date(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(GEN.main(["--check"]), 0)


class EnglishGerman(unittest.TestCase):
    def test_same_keys(self):
        self.assertEqual({p for p, _ in leaves(EN)}, {p for p, _ in leaves(DE)})

    def test_same_placeholders(self):
        de = dict(leaves(DE))
        for path, en in leaves(EN):
            self.assertEqual(set(PLACEHOLDER.findall(en)), set(PLACEHOLDER.findall(de[path])), ".".join(path))

    def test_no_empty_or_padded_texts(self):
        for tree in (EN, DE):
            for path, text in leaves(tree):
                self.assertTrue(isinstance(text, str) and text and text == text.strip(), ".".join(path))

    def test_states_and_units_have_no_placeholders(self):
        for path, text in leaves(EN):
            if "state" in path or "unit_of_measurement" in path:
                self.assertFalse(PLACEHOLDER.search(text), ".".join(path))

    def test_german_is_informal(self):
        for path, text in leaves(DE):
            self.assertNotRegex(text, r"\b(Sie|Ihre|Ihren|Ihr)\b", ".".join(path))


class SensorsAndStates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stubs.load_full()
        cls.sensor = importlib.import_module(f"{stubs.NAME}.sensor")
        cls.labels = importlib.import_module(f"{stubs.NAME}.labels")

    def test_descriptor_keys_equal_translated_sensors(self):
        keys = {d.translation_key for d in self.sensor.SENSORS} | {"key_expires", *self.sensor.HISTORY_UNITS}
        for tree in (EN, DE):
            self.assertEqual(set(tree["entity"]["sensor"]), keys)
            for key, node in tree["entity"]["sensor"].items():
                self.assertTrue(node.get("name"), key)

    def test_every_enum_state_is_translated_and_valid(self):
        enums = [d for d in self.sensor.SENSORS if d.options is not None]
        self.assertTrue(enums)
        for d in enums:
            if d.labels is None:
                # open_enum: Garmin's values are not known yet, so the option list starts empty and has no translations.
                self.assertEqual(list(d.options), [], d.key)
                for tree in (EN, DE):
                    self.assertNotIn("state", tree["entity"]["sensor"][d.translation_key], d.key)
                continue
            self.assertIn(d.labels, self.labels.LABELS)
            for tree in (EN, DE):
                states = tree["entity"]["sensor"][d.translation_key]["state"]
                self.assertEqual(set(states), set(d.options), d.key)
            for option in d.options:
                self.assertRegex(option, STATE_KEY, f"{d.key}: {option}")

    def test_only_known_open_enums(self):
        # A sensor with an empty option list is a deliberate choice (no observed values); keep the list explicit.
        open_enums = {d.key for d in self.sensor.SENSORS if d.options is not None and d.labels is None}
        self.assertEqual(open_enums, {"sleep_breathing_disruption"})

    def test_label_texts_are_pairs_of_non_empty_strings(self):
        for name, words in self.labels.LABELS.items():
            for key, pair in words.items():
                self.assertEqual(key, key.lower(), f"{name}.{key}")
                self.assertEqual(len(pair), 2)
                self.assertTrue(all(isinstance(x, str) and x for x in pair), f"{name}.{key}")

    def test_no_state_block_for_sensors_without_labels(self):
        plain = {d.translation_key for d in self.sensor.SENSORS if d.options is None or d.labels is None} | {"key_expires", *self.sensor.HISTORY_UNITS}
        for key in plain:
            self.assertNotIn("state", EN["entity"]["sensor"][key], key)

    def test_stress_has_no_unknown_state(self):
        # "unknown" is Home Assistant's own state; a Garmin value must not collide with it.
        self.assertNotIn("unknown", self.labels.LABELS["stress"])
        for key, states in ((k, v.get("state", {})) for k, v in EN["entity"]["sensor"].items()):
            self.assertNotIn("unknown", states, key)
            self.assertNotIn("unavailable", states, key)


class OtherEntitiesAndMessages(unittest.TestCase):
    def test_platform_translation_keys_match_code(self):
        for platform in ("binary_sensor", "calendar", "event"):
            used = set(re.findall(r'_attr_translation_key = "([a-z0-9_]+)"', code_text(f"{platform}.py")))
            for tree in (EN, DE):
                self.assertEqual(set(tree["entity"][platform]), used, platform)

    def test_event_types_match_code(self):
        const = code_text("const.py")
        value = re.search(r'EVENT_ACTIVITY_FINISHED[^=]*= "([a-z_]+)"', const).group(1)
        for tree in (EN, DE):
            states = tree["entity"]["event"]["activity"]["state_attributes"]["event_type"]["state"]
            self.assertEqual(set(states), {value})

    @staticmethod
    def raised_keys():
        """translation_key literals plus the ERR_* constants of services.py (passed on as keys)."""
        source = code_text(*[p.name for p in PKG.glob("*.py")])
        keys = set(re.findall(r'(?<![a-z_])translation_key\s*=\s*"([a-z0-9_]+)"', source))
        return keys | set(re.findall(r'^ERR_[A-Z_]+ = "([a-z0-9_]+)"', source, re.M))

    def test_exception_keys_are_used_in_code(self):
        used = self.raised_keys()
        for tree in (EN, DE):
            for key, node in tree["exceptions"].items():
                self.assertIn("message", node)
                self.assertIn(key, used, f"exceptions.{key} is never raised")

    def test_exceptions_raised_with_a_key_exist(self):
        known = set(EN["exceptions"]) | set(EN["issues"]) | {"key_validity", "endpoint"}
        # entity/sensor keys also appear as translation_key; leave out those
        entity_keys = {k for p in EN["entity"].values() for k in p}
        missing = self.raised_keys() - known - entity_keys
        self.assertFalse(missing, f"translation_key without a translation: {sorted(missing)}")

    def test_exception_placeholders_are_passed_by_the_code(self):
        source = code_text("services.py")
        for key, node in EN["exceptions"].items():
            if key == "auth_failed":
                continue
            const = re.search(rf'^(ERR_[A-Z_]+) = "{key}"', source, re.M).group(1)
            for call in re.findall(rf"_(?:invalid|failed)\({const}([^\n]*)\)", source):
                for name in PLACEHOLDER.findall(node["message"]):
                    self.assertIn(f"{name}=", call, f"{key}: placeholder {name} is not passed")

    def test_issue_placeholders_are_passed_by_the_code(self):
        source = code_text("repairs.py")
        for key in ("key_expiring", "key_expired"):
            for tree in (EN, DE):
                for part in tree["issues"][key].values():
                    for name in PLACEHOLDER.findall(part):
                        self.assertIn(f'"{name}":', source, f"{key}: {name}")

    def test_endpoint_options_match_services_yaml(self):
        yaml_text = (PKG / "services.yaml").read_text()
        options = re.findall(r"^\s+- ([a-z_0-9]+)$", yaml_text.split("options:")[1].split("date:")[0], re.M)
        self.assertEqual(len(options), 25)
        for tree in (EN, DE):
            self.assertEqual(set(tree["selector"]["endpoint"]["options"]), set(options))

    def test_icons_json_covers_every_listed_sensor(self):
        icons = json.loads((PKG / "icons.json").read_text())
        self.assertEqual(len(icons["entity"]["sensor"]), 45)
        self.assertLessEqual(set(icons["entity"]["sensor"]), set(EN["entity"]["sensor"]))
        for node in icons["entity"]["sensor"].values():
            self.assertRegex(node["default"], r"^mdi:[a-z0-9-]+$")

    def test_config_flow_texts_use_the_placeholders_the_flow_passes(self):
        source = code_text("config_flow.py")
        passed = set(re.findall(r'"([a-z_]+)":', source[source.index("description_placeholders"):]))
        for tree in (EN, DE):
            for step in tree["config"]["step"].values():
                for name in PLACEHOLDER.findall(step.get("description", "")):
                    self.assertIn(name, passed | {"key_url", "account", "expires"}, name)

    def test_issues_have_a_title_and_exactly_one_body(self):
        for tree in (EN, DE):
            for key, node in tree["issues"].items():
                self.assertIn("title", node, key)
                self.assertEqual(len({"description", "fix_flow"} & set(node)), 1, key)
        self.assertIn("key_expiring", EN["issues"])

    def test_data_description_only_for_existing_fields(self):
        for tree in (EN, DE):
            for flow in ("config", "options"):
                for step, node in tree[flow]["step"].items():
                    self.assertLessEqual(set(node.get("data_description", {})), set(node.get("data", {})), f"{flow}.{step}")

    def test_config_flow_errors_and_aborts_exist(self):
        source = code_text("config_flow.py")
        errors = set(re.findall(r'errors\["base"\] = "([a-z_]+)"', source)) | set(re.findall(r'"base": "([a-z_]+)"', source))
        aborts = set(re.findall(r'(?:async_abort\(reason=|abort_reason=)"([a-z_]+)"', source))
        for tree in (EN, DE):
            self.assertLessEqual(errors, set(tree["config"]["error"]))
            self.assertLessEqual(aborts, set(tree["config"]["abort"]))

    def test_services_and_fields_are_translated(self):
        text = (PKG / "services.yaml").read_text()
        services: dict[str, set[str]] = {}
        current = None
        in_fields = False
        for line in text.splitlines():
            if re.match(r"^[a-z_]+:\s*$", line):
                current = line.rstrip(":\n").strip()
                services[current] = set()
                in_fields = False
            elif re.match(r"^  fields:\s*$", line):
                in_fields = True
            elif re.match(r"^  [a-z_]+:", line):
                in_fields = False
            elif in_fields and (m := re.match(r"^    ([a-z_0-9]+):\s*$", line)):
                services[current].add(m.group(1))
        self.assertTrue(services)
        for tree in (EN, DE):
            self.assertEqual(set(tree["services"]), set(services))
            for name, fields in services.items():
                node = tree["services"][name]
                self.assertTrue(node.get("name") and node.get("description"), name)
                self.assertEqual(set(node.get("fields", {})), fields, name)


class GeneratorParser(unittest.TestCase):
    def test_finds_labels_across_line_breaks_and_without_indent(self):
        src = (
            'SENSORS = (\n'
            '    _d("a", "daily", f, labels="x"),\n'
            '_d("b", "daily", f,\n    unit=1,\n    labels=\n    "y", open_enum=True),\n'
            '    _d("c", "daily", f),\n)\n'
        )
        self.assertEqual(GEN.parse_descriptors(src), [("a", "x", False), ("b", "y", True), ("c", None, False)])

    def test_non_literal_arguments_fail_loudly(self):
        with self.assertRaises(GEN.GeneratorError):
            GEN.parse_descriptors('_d("a", "daily", f, labels=NAME)')
        with self.assertRaises(GEN.GeneratorError):
            GEN.parse_descriptors("_d(key, 'daily', f)")

    def test_all_real_descriptors_found(self):
        count = len(re.findall(r"^\s*_d\(", (PKG / "sensor.py").read_text(), re.M))
        self.assertEqual(len(GEN.parse_descriptors((PKG / "sensor.py").read_text())), count)


if __name__ == "__main__":
    unittest.main()
