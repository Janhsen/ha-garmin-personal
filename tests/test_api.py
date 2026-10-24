import asyncio
import base64
import json
import sys
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _load import load  # noqa: E402

gp = load()
api = gp.api


def jwt(exp: datetime) -> str:
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64({'exp': int(exp.timestamp())})}.sig"


class Resp:
    def __init__(self, status=200, body="", headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    async def text(self):
        return self.body if isinstance(self.body, str) else self.body.decode()

    async def read(self):
        return self.body if isinstance(self.body, bytes) else self.body.encode()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    """Scripted responses per (method, path); records every call."""

    def __init__(self):
        self.script = {}
        self.calls = []

    def add(self, method, path, *responses):
        self.script[(method, path)] = list(responses)

    def _do(self, method, url, **kw):
        path = url.split("garmin.com", 1)[1]
        self.calls.append((method, path, kw))
        queue = self.script[(method, path)]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, **kw):
        return self._do("GET", url, **kw)

    def post(self, url, **kw):
        return self._do("POST", url, **kw)


TOKEN_PATH = gp.const.KEY_EXCHANGE_PATH


def make(session):
    async def nosleep(_):
        return None

    return api.GarminPersonalApi(session, "KEY", base_url="https://x.garmin.com", sleep=nosleep)


def run(coro):
    return asyncio.run(coro)


class SplitRange(unittest.TestCase):
    def test_windows(self):
        w = api.split_range(date(2026, 1, 1), date(2026, 3, 1), 31)
        self.assertEqual(w[0], (date(2026, 1, 1), date(2026, 1, 31)))
        self.assertEqual(w[1], (date(2026, 2, 1), date(2026, 3, 3 - 2)))
        self.assertEqual(w[-1][1], date(2026, 3, 1))

    def test_single_day(self):
        self.assertEqual(api.split_range(date(2026, 1, 1), date(2026, 1, 1), 28), [(date(2026, 1, 1),) * 2])

    def test_no_gaps_or_overlap(self):
        w = api.split_range(date(2025, 1, 1), date(2026, 1, 1), 28)
        for (_, e), (s, _) in zip(w, w[1:]):
            self.assertEqual(s, e + timedelta(days=1))
        self.assertTrue(all((e - s).days + 1 <= 28 for s, e in w))

    def test_errors(self):
        with self.assertRaises(ValueError):
            api.split_range(date(2026, 2, 1), date(2026, 1, 1), 5)


class Filters(unittest.TestCase):
    def test_friendly_and_garmin_names(self):
        p = dict(api.activity_filter_params({"activity_type": "running", "minDistance": 5}))
        self.assertEqual(p["activityType"], "running")
        self.assertEqual(p["minDistance"], "5")

    def test_dates_and_favorite(self):
        p = dict(api.activity_filter_params({"start_date": date(2026, 1, 2), "favorite": True}))
        self.assertEqual(p["startDate"], "2026-01-02")
        self.assertEqual(p["favorite"], "1")

    def test_bounding_box(self):
        p = dict(api.activity_filter_params({"bounding_box": {"north": 1, "east": 2, "south": 3, "west": 4}}))
        self.assertEqual(p["upperLatitude"], "1")
        self.assertEqual(p["leftLongitude"], "4")

    def test_unknown(self):
        with self.assertRaises(ValueError):
            api.activity_filter_params({"nonsense": 1})


class Token(unittest.TestCase):
    def test_exchange_and_reuse(self):
        s = FakeSession()
        tok = jwt(datetime.now(UTC) + timedelta(hours=24))
        s.add("POST", TOKEN_PATH, Resp(200, f'"{tok}"'))
        s.add("GET", "/userprofile-service/userprofile/settings", Resp(200, '{"displayName": "example-user"}'))
        c = make(s)
        run(c.get_profile_settings())
        run(c.get_profile_settings())
        posts = [x for x in s.calls if x[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(s.calls[0][2]["headers"]["Authorization"], "ApiKey KEY")
        self.assertEqual(s.calls[1][2]["headers"]["Authorization"], f"Bearer {tok}")

    def test_expiring_token_is_renewed(self):
        s = FakeSession()
        old = jwt(datetime.now(UTC) + timedelta(minutes=2))
        new = jwt(datetime.now(UTC) + timedelta(hours=24))
        s.add("POST", TOKEN_PATH, Resp(200, old), Resp(200, new))
        s.add("GET", "/userprofile-service/userprofile/settings", Resp(200, "{}"))
        c = make(s)
        run(c.get_profile_settings())
        run(c.get_profile_settings())
        self.assertEqual(len([x for x in s.calls if x[0] == "POST"]), 2)

    def test_rejected_key(self):
        s = FakeSession()
        s.add("POST", TOKEN_PATH, Resp(401, "no"))
        with self.assertRaises(api.GarminAuthError):
            run(make(s).async_validate())

    def test_empty_key(self):
        with self.assertRaises(api.GarminAuthError):
            api.GarminPersonalApi(FakeSession(), "  ")

    def test_401_refreshes_once(self):
        s = FakeSession()
        tok = jwt(datetime.now(UTC) + timedelta(hours=24))
        s.add("POST", TOKEN_PATH, Resp(200, tok))
        s.add("GET", "/userprofile-service/userprofile/settings", Resp(401), Resp(200, '{"a": 1}'))
        self.assertEqual(run(make(s).get_profile_settings()), {"a": 1})
        self.assertEqual(len([x for x in s.calls if x[0] == "POST"]), 2)

    def test_401_twice_is_auth_error(self):
        s = FakeSession()
        tok = jwt(datetime.now(UTC) + timedelta(hours=24))
        s.add("POST", TOKEN_PATH, Resp(200, tok))
        s.add("GET", "/userprofile-service/userprofile/settings", Resp(401))
        with self.assertRaises(api.GarminAuthError):
            run(make(s).get_profile_settings())


class Requests(unittest.TestCase):
    def setUp(self):
        self.s = FakeSession()
        self.s.add("POST", TOKEN_PATH, Resp(200, jwt(datetime.now(UTC) + timedelta(hours=24))))

    def test_retry_then_success(self):
        self.s.add("GET", "/userprofile-service/userprofile/settings", Resp(503), Resp(200, '{"ok": true}'))
        self.assertEqual(run(make(self.s).get_profile_settings()), {"ok": True})

    def test_retry_exhausted(self):
        self.s.add("GET", "/userprofile-service/userprofile/settings", Resp(500))
        with self.assertRaises(api.GarminApiError) as cm:
            run(make(self.s).get_profile_settings())
        self.assertEqual(cm.exception.status, 500)
        self.assertEqual(len([x for x in self.s.calls if x[0] == "GET"]), gp.const.MAX_RETRIES + 1)

    def test_429_raises_rate_limit(self):
        self.s.add("GET", "/userprofile-service/userprofile/settings", Resp(429, headers={"Retry-After": "9999"}))
        with self.assertRaises(api.GarminRateLimitError):
            run(make(self.s).get_profile_settings())

    def test_204_is_none(self):
        self.s.add("GET", "/userprofile-service/userprofile/settings", Resp(204))
        self.assertIsNone(run(make(self.s).get_profile_settings()))

    def test_network_error_retried(self):
        self.s.add("GET", "/userprofile-service/userprofile/settings", OSError("boom"), Resp(200, "{}"))
        self.assertEqual(run(make(self.s).get_profile_settings()), {})

    def test_bad_json(self):
        self.s.add("GET", "/userprofile-service/userprofile/settings", Resp(200, "<html>"))
        with self.assertRaises(api.GarminApiError):
            run(make(self.s).get_profile_settings())

    def test_other_host_refused(self):
        with self.assertRaises(ValueError):
            run(make(self.s)._request("https://evil.example/x"))

    def test_download_uses_zip_accept(self):
        self.s.add("GET", "/download-service/files/activity/42", Resp(200, b"PK\x03\x04"))
        data = run(make(self.s).download_activity_zip(42))
        self.assertEqual(data, b"PK\x03\x04")
        self.assertEqual(self.s.calls[-1][2]["headers"]["Accept"], api.ZIP)

    def test_activity_id_must_be_positive(self):
        with self.assertRaises(ValueError):
            run(make(self.s).get_activity(0))


class Paging(unittest.TestCase):
    def test_pages_until_limit(self):
        s = FakeSession()
        s.add("POST", TOKEN_PATH, Resp(200, jwt(datetime.now(UTC) + timedelta(hours=24))))
        path = "/activitylist-service/activities/search/activities"
        s.add("GET", path, Resp(200, json.dumps([{"activityId": i} for i in range(45)])),
              Resp(200, json.dumps([{"activityId": i} for i in range(45, 60)])))
        got = run(make(s).search_activities(limit=100))
        self.assertEqual(len(got), 60)
        gets = [c for c in s.calls if c[0] == "GET"]
        self.assertEqual(dict(gets[0][2]["params"])["limit"], "45")
        self.assertEqual(dict(gets[1][2]["params"])["start"], "45")

    def test_limit_trimmed(self):
        s = FakeSession()
        s.add("POST", TOKEN_PATH, Resp(200, jwt(datetime.now(UTC) + timedelta(hours=24))))
        s.add("GET", "/activitylist-service/activities/search/activities",
              Resp(200, json.dumps([{"activityId": i} for i in range(10)])))
        self.assertEqual(len(run(make(s).search_activities(limit=10))), 10)


class Windows(unittest.TestCase):
    def test_stress_split_in_28_day_windows(self):
        calls = []

        async def fake_request(path, params=None, **kw):
            calls.append(dict(params or ()))
            return [{"x": 1}]

        c = make(FakeSession())
        c._request = fake_request
        out = run(c.get_stress(date(2026, 1, 1), date(2026, 3, 31)))
        self.assertEqual(len(calls), 4)  # 90 days in windows of 28
        self.assertEqual(len(out), 4)

    def test_weight_range_merges(self):
        c = make(FakeSession())
        pages = iter([
            {"dailyWeightSummaries": [{"summaryDate": "a"}], "totalAverage": 1},
            {"dailyWeightSummaries": [{"summaryDate": "b"}], "nextDateWeight": 2},
        ])

        async def fake_request(path, params=None, **kw):
            return next(pages)

        c._request = fake_request
        out = run(c.get_weight_range(date(2025, 1, 1), date(2026, 6, 1)))
        self.assertEqual([d["summaryDate"] for d in out["dailyWeightSummaries"]], ["a", "b"])
        self.assertEqual(out["totalAverage"], 1)
        self.assertEqual(out["nextDateWeight"], 2)


class FetchDispatch(unittest.TestCase):
    def test_every_endpoint_name_is_dispatched(self):
        c = make(FakeSession())
        seen = []

        async def fake_request(path, params=None, **kw):
            seen.append(path)
            return {}

        c._request = fake_request
        for name in api.ENDPOINT_NAMES:
            run(c.fetch(name, day=date(2026, 5, 1), activity_id=7))
        self.assertGreaterEqual(len(seen), len(api.ENDPOINT_NAMES))

    def test_unknown(self):
        with self.assertRaises(ValueError):
            run(make(FakeSession()).fetch("nope"))

    def test_activity_needs_id(self):
        with self.assertRaises(ValueError):
            run(make(FakeSession()).fetch("activity"))


if __name__ == "__main__":
    unittest.main()
