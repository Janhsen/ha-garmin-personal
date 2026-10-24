"""hassfest rejects translation strings that look like HTML (e.g. ``<name>``)."""

import json
import pathlib
import re
import unittest

BASE = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "garmin_personal"
TAG = re.compile(r"<[A-Za-z/!][^>]*>")


def strings(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from strings(value, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


class NoHtml(unittest.TestCase):
    def test_no_tag_like_text(self):
        bad = []
        for name in ("strings.json", "translations/en.json", "translations/de.json"):
            data = json.loads((BASE / name).read_text(encoding="utf-8"))
            bad += [f"{name}{p}" for p, s in strings(data) if TAG.search(s)]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
