"""api.py: Antwortformen, Token-Austausch (429/5xx/403), gemeinsame Sperre, parallele 401, today."""

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


def good_token(tag=0):
    return jwt(datetime.now(UTC) + timedelta(hours=24 + tag))


class Resp:
    def __init__(self, status=200, body="", headers=None, delay=False):
        self.status, self.body, self.headers, self.delay = status, body, headers or {}, delay

    async def text(self):
        return self.body

    async def read(self):
        return self.body.encode()

    async def __aenter__(self):
        if self.delay:
            await asyncio.sleep(0)
        return self

    async def __aexit__(self, *a):
        return False


class Session:
    """POST gives the queued token answers, GET answers per path from a function."""

    def __init__(self, posts, get=None):
        self.posts = list(posts)
        self.get_fn = get or (lambda path, headers: Resp(200, "{}"))
        self.post_count = 0
        self.get_count = 0

    def post(self, url, **kw):
        self.post_count += 1
        return self.posts.pop(0) if len(self.posts) > 1 else self.posts[0]

    def get(self, url, **kw):
        self.get_count += 1
        return self.get_fn(url.split("garmin.com", 1)[1], kw["headers"])


def make(session):
    async def nosleep(_):
        return None

    return api.GarminPersonalApi(session, "KEY", base_url="https://x.garmin.com", sleep=nosleep)


def run(coro):
    return asyncio.run(coro)


class WrongShapes(unittest.TestCase):
    def client(self, payload):
        return make(Session([Resp(200, good_token())], lambda p, h: Resp(200, json.dumps(payload))))

    def test_hrv_summaries_list_instead_of_object(self):
        with self.assertRaises(api.GarminApiError):
            run(self.client([1, 2]).get_hrv_summaries(date(2026, 5, 1), date(2026, 5, 3)))

    def test_hrv_summaries_field_not_a_list(self):
        with self.assertRaises(api.GarminApiError):
            run(self.client({"hrvSummaries": "x"}).get_hrv_summaries(date(2026, 5, 1), date(2026, 5, 3)))

    def test_daily_summaries_scalar(self):
        with self.assertRaises(api.GarminApiError):
            run(self.client(5).get_daily_summaries(date(2026, 5, 1), date(2026, 5, 3)))

    def test_weight_range_list_and_bad_field(self):
        with self.assertRaises(api.GarminApiError):
            run(self.client([{"a": 1}]).get_weight_range(date(2026, 5, 1), date(2026, 5, 3)))
        with self.assertRaises(api.GarminApiError):
            run(self.client({"dailyWeightSummaries": {"a": 1}}).get_weight_range(
                date(2026, 5, 1), date(2026, 5, 3)))

    def test_activity_search_non_list(self):
        with self.assertRaises(api.GarminApiError):
            run(self.client({"error": "x"}).search_activities_page(0, 5))

    def test_valid_shapes_and_empty_answers_still_work(self):
        c = self.client({"hrvSummaries": [{"a": 1}]})
        self.assertEqual(run(c.get_hrv_summaries(date(2026, 5, 1), date(2026, 5, 3))), [{"a": 1}])
        c = make(Session([Resp(200, good_token())], lambda p, h: Resp(204, "")))
        self.assertEqual(run(c.get_hrv_summaries(date(2026, 5, 1), date(2026, 5, 3))), [])
        self.assertEqual(run(c.search_activities_page(0, 5)), [])


class TokenExchange(unittest.TestCase):
    def test_429_is_rate_limit_with_retry_after_and_no_hammering(self):
        s = Session([Resp(429, "", {"Retry-After": "900"})])
        c = make(s)
        with self.assertRaises(api.GarminRateLimitError) as ctx:
            run(c.get_json("/a"))
        self.assertEqual(ctx.exception.retry_after, 900)
        posts = s.post_count
        # every further call (any endpoint, any group) fails at once, without a new exchange
        for path in ("/b", "/c"):
            with self.assertRaises(api.GarminRateLimitError) as again:
                run(c.get_json(path))
            self.assertGreater(again.exception.retry_after, 0)
        self.assertEqual(s.post_count, posts)
        self.assertEqual(s.get_count, 0)

    def test_429_with_short_retry_after_is_retried(self):
        s = Session([Resp(429, "", {"Retry-After": "1"}), Resp(200, good_token())])
        run(make(s).get_json("/a"))
        self.assertEqual(s.post_count, 2)

    def test_503_is_retried_then_succeeds(self):
        s = Session([Resp(503), Resp(503), Resp(200, good_token())])
        run(make(s).get_json("/a"))
        self.assertEqual(s.post_count, 3)

    def test_persistent_503_is_api_error_with_cooldown(self):
        s = Session([Resp(503)])
        c = make(s)
        with self.assertRaises(api.GarminApiError) as ctx:
            run(c.get_json("/a"))
        self.assertNotIsInstance(ctx.exception, api.GarminAuthError)
        posts = s.post_count
        with self.assertRaises(api.GarminApiError):
            run(c.get_json("/b"))
        self.assertEqual(s.post_count, posts)  # the next endpoint does not try again

    def test_cooldown_ends(self):
        s = Session([Resp(503), Resp(503), Resp(503), Resp(200, good_token())])
        c = make(s)
        with self.assertRaises(api.GarminApiError):
            run(c.get_json("/a"))
        c._blocked_until = 0.0  # time has passed
        run(c.get_json("/b"))

    def test_401_is_auth_error(self):
        with self.assertRaises(api.GarminAuthError):
            run(make(Session([Resp(401, "no")])).get_json("/a"))

    def test_403_html_is_not_an_invalid_key(self):
        for body, headers in (("<html>blocked</html>", {}), ("denied", {"Content-Type": "text/html"})):
            s = Session([Resp(403, body, headers)])
            with self.assertRaises(api.GarminApiError) as ctx:
                run(make(s).get_json("/a"))
            self.assertNotIsInstance(ctx.exception, api.GarminAuthError)
            self.assertEqual(ctx.exception.status, 403)

    def test_403_plain_or_empty_is_still_auth(self):
        for body in ("", '{"message":"Forbidden"}'):
            with self.assertRaises(api.GarminAuthError):
                run(make(Session([Resp(403, body)])).get_json("/a"))

    def test_html_with_status_200_is_not_taken_as_token(self):
        s = Session([Resp(200, "<html>maintenance</html>")])
        with self.assertRaises(api.GarminApiError):
            run(make(s).get_json("/a"))


class SharedBlock(unittest.TestCase):
    def test_429_on_a_data_endpoint_blocks_all_endpoints(self):
        s = Session([Resp(200, good_token())], lambda p, h: Resp(429, "", {"Retry-After": "900"}))
        c = make(s)
        with self.assertRaises(api.GarminRateLimitError) as ctx:
            run(c.get_json("/a"))
        self.assertEqual(ctx.exception.retry_after, 900)
        gets = s.get_count
        with self.assertRaises(api.GarminRateLimitError):
            run(c.get_json("/other"))
        self.assertEqual(s.get_count, gets)

    def test_429_without_retry_after_uses_default(self):
        s = Session([Resp(200, good_token())], lambda p, h: Resp(429))
        c = make(s)
        with self.assertRaises(api.GarminRateLimitError) as ctx:
            run(c.get_json("/a"))
        self.assertEqual(ctx.exception.retry_after, api.RATE_LIMIT_DEFAULT_BLOCK)

    def test_block_expires(self):
        s = Session([Resp(200, good_token())], lambda p, h: Resp(429, "", {"Retry-After": "900"}))
        c = make(s)
        with self.assertRaises(api.GarminRateLimitError):
            run(c.get_json("/a"))
        c._blocked_until = 0.0
        s.get_fn = lambda p, h: Resp(200, "{}")
        self.assertEqual(run(c.get_json("/a")), {})


class ParallelUnauthorized(unittest.TestCase):
    def test_two_simultaneous_401_cause_one_new_exchange(self):
        tokens = [good_token(0), good_token(1), good_token(2)]
        s = Session([Resp(200, t) for t in tokens])

        def get(path, headers):
            if headers["Authorization"] == f"Bearer {tokens[0]}":
                return Resp(401, "", delay=True)
            return Resp(200, "{}")

        s.get_fn = get
        c = make(s)

        async def both():
            return await asyncio.gather(c.get_json("/a"), c.get_json("/b"))

        self.assertEqual(run(both()), [{}, {}])
        self.assertEqual(s.post_count, 2)  # first token + exactly one replacement


class FetchToday(unittest.TestCase):
    @staticmethod
    def recorded(**kw):
        c = make(Session([Resp(200, good_token())]))
        seen = []

        async def fake_request(path, params=None, **_):
            seen.append((path, params))
            return {}

        c._request = fake_request
        for name in kw.pop("names"):
            run(c.fetch(name, **kw))
        return seen

    def test_default_day_comes_from_the_caller(self):
        seen = self.recorded(names=["hrv", "hydration", "menstrual_day"], today=date(2030, 1, 2))
        self.assertTrue(seen[0][0].endswith("/2030-01-02"))
        self.assertIn("2030-01-02", seen[1][0])
        self.assertIn(("todayDate", "2030-01-02"), seen[2][1])

    def test_explicit_day_wins_over_today(self):
        seen = self.recorded(names=["hrv"], today=date(2030, 1, 2), day=date(2029, 12, 31))
        self.assertTrue(seen[0][0].endswith("/2029-12-31"))


if __name__ == "__main__":
    unittest.main()
