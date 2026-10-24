"""Key paths of a Garmin API response (names only, never values), for spotting new or removed fields.

python3 -I scripts/api_fields.py FILE [FILE ...]   prints the sorted key paths of the JSON data
python3 -I scripts/api_fields.py --diff BASELINE FILE [FILE ...]   prints added (+) and removed (-) paths

FILE is either a raw JSON response or a Home Assistant service response with ``service_response.data``.
List items are folded into ``[]``. Only key names are read, so the baseline holds no personal data.
"""

import json
import sys


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


def main(argv):
    if argv and argv[0] == "--diff":
        base = set(json.load(open(argv[1])))
        now = set().union(*(paths(load(f)) for f in argv[2:]))
        for p in sorted(now - base):
            print("+", p)
        for p in sorted(base - now):
            print("-", p)
        return
    print("\n".join(sorted(set().union(*(paths(load(f)) for f in argv)))))


if __name__ == "__main__":
    main(sys.argv[1:])
