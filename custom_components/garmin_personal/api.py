"""Async client for the Garmin Connect Personal API.

The Personal API works in two steps: a long-lived API key (created in Garmin
Connect) is exchanged for a 24 hour bearer token, which is sent with every data
request. There are no refresh tokens, the key is simply exchanged again.

This module does not import Home Assistant, so it can be tested on its own.
Responses are returned as the decoded JSON that Garmin sends (camelCase keys);
the entities pick out the values they need.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

try:  # aiohttp is always present inside Home Assistant
    from aiohttp import ClientError, ClientTimeout

    REQUEST_TIMEOUT: Any = ClientTimeout(total=30)
except ImportError:  # pragma: no cover - only in stripped-down test environments
    ClientError = OSError  # type: ignore[assignment,misc]
    REQUEST_TIMEOUT = None

from .const import (
    ACTIVITY_PAGE_DEFAULT,
    ACTIVITY_PAGE_MAX,
    ACTIVITY_SEARCH_MAX_TOTAL,
    DEFAULT_BASE_URL,
    FALLBACK_TOKEN_LIFETIME,
    KEY_EXCHANGE_PATH,
    MAX_DAYS_BODY_BATTERY,
    MAX_DAYS_DAILY_SUMMARIES,
    MAX_DAYS_HRV,
    MAX_DAYS_HYDRATION,
    MAX_DAYS_SLEEP,
    MAX_DAYS_STEPS,
    MAX_DAYS_STRESS,
    MAX_DAYS_WEIGHT,
    MAX_DAYS_WELLNESS_ACTIVITIES,
    MAX_RETRIES,
    MAX_RETRY_AFTER,
    RETRY_STATUSES,
    TOKEN_REFRESH_MARGIN,
)

_LOGGER = logging.getLogger(__name__)

# Back-off shared by all callers of one client (kept here, not in const.py: internal tuning).
RATE_LIMIT_DEFAULT_BLOCK = 60.0  # seconds, when Garmin sends 429 without Retry-After
EXCHANGE_COOLDOWN = 30.0  # seconds without a new token exchange after a failed one
MAX_BLOCK = 3600.0  # never block longer than this, whatever Retry-After says

JSON = "application/json"
ZIP = "application/x-zip-compressed"  # Garmin answers HTTP 406 for application/octet-stream


class GarminError(Exception):
    """Base error of this client."""


class GarminAuthError(GarminError):
    """The API key was rejected (expired, deleted or mistyped)."""


class GarminRateLimitError(GarminError):
    """Garmin answered HTTP 429 (``retry_after`` in seconds when known)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class GarminApiError(GarminError):
    """Any other failed request."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def jwt_expiry(token: str) -> datetime | None:
    """Read the ``exp`` claim of a JWT without verifying the signature."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        exp = json.loads(payload)["exp"]
        return datetime.fromtimestamp(float(exp), tz=UTC)
    except (binascii.Error, ValueError, KeyError, TypeError, OverflowError, OSError):
        return None


def split_range(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    """Split ``start..end`` (inclusive) into windows of at most ``max_days`` days."""
    if end < start:
        raise ValueError("end date is before start date")
    if max_days < 1:
        raise ValueError("max_days must be at least 1")
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=max_days - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def parse_day(value: date | datetime | str) -> date:
    """Accept ``date``, ``datetime`` or ``YYYY-MM-DD``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as err:
        raise ValueError(f"not a date: {value!r}") from err


# Friendly (snake_case) activity filters -> Garmin query parameter names.
_SCALAR_FILTERS: dict[str, str] = {
    "activity_type": "activityType",
    "activity_subtype": "activitySubType",
    "event_type": "eventType",
    "search": "search",
    "sort_by": "sortBy",
    "sort_order": "sortOrder",
    "min_distance": "minDistance",
    "max_distance": "maxDistance",
    "min_duration": "minDuration",
    "max_duration": "maxDuration",
    "min_elapsed_duration": "minElapsedDuration",
    "max_elapsed_duration": "maxElapsedDuration",
    "min_elevation": "minElevation",
    "max_elevation": "maxElevation",
    "min_avg_power": "minAvgPower",
    "lower_max_depth": "lowerMaxDepth",
    "upper_max_depth": "upperMaxDepth",
    "min_bottom_time": "minBottomTime",
    "max_bottom_time": "maxBottomTime",
}
_BOOL_FILTERS: dict[str, str] = {"exclude_children": "excludeChildren", "deco_dive": "decoDive"}
_LIST_FILTERS: dict[str, str] = {
    "excluded_activity_subtypes": "excludedActivitySubType",
    "required_fields": "requiredField",
}
_KNOWN_API_NAMES = frozenset(
    [*_SCALAR_FILTERS.values(), *_BOOL_FILTERS.values(), *_LIST_FILTERS.values()]
)


def activity_filter_params(filters: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """Translate activity filters into query parameters.

    Accepts the friendly snake_case names (``min_distance``) as well as Garmin's
    own names (``minDistance``). Dates, ``favorite`` and ``bounding_box`` are
    handled specially. Raises ``ValueError`` for unknown names.
    """
    params: list[tuple[str, str]] = []
    for name, value in (filters or {}).items():
        if value is None:
            continue
        if name in ("start_date", "startDate"):
            params.append(("startDate", parse_day(value).isoformat()))
        elif name in ("end_date", "endDate"):
            params.append(("endDate", parse_day(value).isoformat()))
        elif name == "favorite":
            params.append(("favorite", "1" if value else "0"))
        elif name == "bounding_box":
            try:
                params += [
                    ("upperLatitude", str(value["north"])),
                    ("rightLongitude", str(value["east"])),
                    ("lowerLatitude", str(value["south"])),
                    ("leftLongitude", str(value["west"])),
                ]
            except (KeyError, TypeError) as err:
                raise ValueError("bounding_box needs north, east, south and west") from err
        elif name in _SCALAR_FILTERS:
            params.append((_SCALAR_FILTERS[name], str(value)))
        elif name in _BOOL_FILTERS:
            params.append((_BOOL_FILTERS[name], "true" if value else "false"))
        elif name in _LIST_FILTERS:
            if isinstance(value, str) or not isinstance(value, Iterable):
                raise ValueError(f"{name} must be a list")
            params += [(_LIST_FILTERS[name], str(item)) for item in value]
        elif name in _KNOWN_API_NAMES or name in (
            "upperLatitude",
            "rightLongitude",
            "lowerLatitude",
            "leftLongitude",
            "favorite",
        ):
            params.append((name, str(value)))
        else:
            raise ValueError(f"unknown activity filter: {name}")
    return params


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(float(value.strip()), 0.0)
    except ValueError:
        return None


def _looks_like_html(body: str, content_type: str | None) -> bool:
    """A web application firewall or maintenance page instead of an API answer."""
    if content_type and "html" in content_type.lower():
        return True
    return body.lstrip()[:1] == "<"


def _plausible_token(token: str) -> bool:
    """Reject bodies that are clearly not a bearer token (HTML, JSON, text with blanks)."""
    return bool(token) and token[0] not in "<{[" and not any(ch.isspace() for ch in token)


def _mapping_or_none(result: Any, what: str) -> Mapping[str, Any] | None:
    """The decoded answer as a mapping; ``None`` stays ``None``, anything else is an API error."""
    if result is None:
        return None
    if isinstance(result, Mapping):
        return result
    raise GarminApiError(f"{what}: unexpected response shape ({type(result).__name__})")


def _list_field(page: Mapping[str, Any], key: str, what: str) -> list[Any]:
    value = page.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise GarminApiError(f"{what}: {key} is not a list")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GarminPersonalApi:
    """Client for all read endpoints of the Garmin Connect Personal API."""

    def __init__(
        self,
        session: Any,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Create the client; ``session`` is an ``aiohttp.ClientSession``."""
        key = api_key.strip()
        if not key:
            raise GarminAuthError("The API key is empty")
        self._session = session
        self._api_key = key
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep
        self._token: str | None = None
        self._token_expires: datetime | None = None
        self._lock = asyncio.Lock()
        # Shared by every caller (all coordinators and the services), so that one
        # answer of HTTP 429 or a failed token exchange stops the requests of all groups.
        self._blocked_until = 0.0
        self._blocked_error: GarminError | None = None

    # -- shared back-off --------------------------------------------------

    def _block(self, seconds: float, error: GarminError) -> None:
        seconds = min(max(seconds, 0.0), MAX_BLOCK)
        self._blocked_until = time.monotonic() + seconds
        self._blocked_error = error

    def _raise_if_blocked(self) -> None:
        remaining = self._blocked_until - time.monotonic()
        if remaining > 0 and self._blocked_error is not None:
            err = self._blocked_error
            if isinstance(err, GarminRateLimitError):
                raise GarminRateLimitError(str(err), remaining)
            raise GarminApiError(str(err), getattr(err, "status", None))

    # -- tokens -----------------------------------------------------------

    def _token_usable(self) -> bool:
        return (
            self._token is not None
            and self._token_expires is not None
            and self._token_expires - datetime.now(UTC) > TOKEN_REFRESH_MARGIN
        )

    async def _exchange_token(self) -> None:
        self._raise_if_blocked()
        headers = {"Authorization": f"ApiKey {self._api_key}", "Accept": "*/*"}
        attempt = 0
        while True:
            try:
                async with self._session.post(
                    self._base_url + KEY_EXCHANGE_PATH, headers=headers, timeout=REQUEST_TIMEOUT
                ) as response:
                    status = response.status
                    text = await response.text()
                    retry_header = response.headers.get("Retry-After")
                    content_type = response.headers.get("Content-Type")
            except (ClientError, TimeoutError) as err:
                if attempt < MAX_RETRIES:
                    await self._sleep(0.5 * 2**attempt)
                    attempt += 1
                    continue
                error = GarminApiError(f"Cannot reach Garmin: {err}")
                self._block(EXCHANGE_COOLDOWN, error)
                raise error from err
            if status == 401:
                raise GarminAuthError(
                    "Garmin rejected the API key (HTTP 401); it may be expired or deleted"
                )
            if status == 403:
                if _looks_like_html(text, content_type):
                    # A protection layer in front of Garmin, not a verdict on the key.
                    error = GarminApiError(
                        "Token exchange blocked by a protection layer (HTTP 403)", 403
                    )
                    self._block(EXCHANGE_COOLDOWN, error)
                    raise error
                raise GarminAuthError(
                    "Garmin rejected the API key (HTTP 403); it may be expired or deleted"
                )
            if status in RETRY_STATUSES:
                delay = _retry_after(retry_header)
                if status != 429 and delay is None:
                    delay = 0.5 * 2**attempt
                if delay is not None and delay <= MAX_RETRY_AFTER and attempt < MAX_RETRIES:
                    await self._sleep(max(delay, 0.5))
                    attempt += 1
                    continue
                if status == 429:
                    wait = delay if delay is not None else RATE_LIMIT_DEFAULT_BLOCK
                    limit_error = GarminRateLimitError(
                        "Garmin rate limit reached during token exchange (HTTP 429)", wait
                    )
                    self._block(wait, limit_error)
                    raise limit_error
                error = GarminApiError(f"Token exchange failed (HTTP {status})", status)
                self._block(delay if delay is not None else EXCHANGE_COOLDOWN, error)
                raise error
            if status >= 400:
                raise GarminApiError(f"Token exchange failed (HTTP {status})", status)
            token = text.strip().strip('"')
            if not token:
                raise GarminApiError("The token endpoint returned an empty body", status)
            if not _plausible_token(token):
                error = GarminApiError("The token endpoint returned an unexpected answer", status)
                self._block(EXCHANGE_COOLDOWN, error)
                raise error
            self._token = token
            self._token_expires = jwt_expiry(token) or (datetime.now(UTC) + FALLBACK_TOKEN_LIFETIME)
            return

    async def _get_token(self, *, force: bool = False, rejected: str | None = None) -> str:
        """Return a usable token.

        ``rejected`` is the token Garmin just answered with 401: it is only exchanged
        again when nobody else has done so in the meantime (parallel requests).
        """
        async with self._lock:
            replaced = rejected is not None and self._token is not None and self._token != rejected
            if (force and not replaced) or not self._token_usable():
                await self._exchange_token()
            assert self._token is not None  # noqa: S101
            return self._token

    async def async_validate(self) -> dict[str, Any]:
        """Check the key by fetching the profile settings."""
        await self._get_token(force=True)
        return await self.get_profile_settings() or {}

    # -- transport --------------------------------------------------------

    async def _request(
        self,
        path: str,
        params: Sequence[tuple[str, str]] | None = None,
        *,
        accept: str = JSON,
        binary: bool = False,
    ) -> Any:
        if not path.startswith("/") or path.startswith("//") or "://" in path:
            raise ValueError("path must be an absolute path on the API host")
        refreshed = False
        attempt = 0
        while True:
            self._raise_if_blocked()
            token = await self._get_token()
            headers = {"Authorization": f"Bearer {token}", "Accept": accept}
            try:
                async with self._session.get(
                    self._base_url + path,
                    params=list(params or ()),
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                ) as response:
                    status = response.status
                    retry_header = response.headers.get("Retry-After")
                    body = await (response.read() if binary else response.text())
            except (ClientError, TimeoutError) as err:
                if attempt < MAX_RETRIES:
                    await self._sleep(0.5 * 2**attempt)
                    attempt += 1
                    continue
                raise GarminApiError(f"Cannot reach Garmin: {err}") from err

            if status == 401 and not refreshed:
                refreshed = True
                await self._get_token(force=True, rejected=token)
                continue
            if status == 401:
                raise GarminAuthError("Garmin keeps rejecting the access token")
            if status in RETRY_STATUSES and attempt < MAX_RETRIES:
                delay = _retry_after(retry_header)
                if delay is None:
                    delay = 0.5 * 2**attempt
                if delay <= MAX_RETRY_AFTER:
                    await self._sleep(max(delay, 0.5))
                    attempt += 1
                    continue
            if status == 429:
                wait = _retry_after(retry_header)
                if wait is None:
                    wait = RATE_LIMIT_DEFAULT_BLOCK
                error = GarminRateLimitError("Garmin rate limit reached (HTTP 429)", wait)
                self._block(wait, error)
                raise error
            if status >= 400:
                raise GarminApiError(f"GET {path} failed (HTTP {status})", status)
            if status == 204 or not body:
                return None
            if binary:
                return body
            try:
                return json.loads(body)
            except ValueError as err:
                raise GarminApiError(f"GET {path} returned invalid JSON") from err

    async def get_json(self, path: str, params: Sequence[tuple[str, str]] | None = None) -> Any:
        """GET any endpoint of the API host and return decoded JSON."""
        return await self._request(path, params)

    async def _ranged(
        self,
        fetch: Callable[[date, date], Awaitable[Any]],
        start: date,
        end: date,
        max_days: int,
    ) -> list[Any]:
        """Run ``fetch`` over windows and concatenate list results."""
        items: list[Any] = []
        for window_start, window_end in split_range(start, end, max_days):
            result = await fetch(window_start, window_end)
            if isinstance(result, list):
                items.extend(result)
            elif result is not None:
                items.append(result)
        return items

    # -- activities -------------------------------------------------------

    async def search_activities_page(
        self, start: int, limit: int, filters: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """One page of ``/activitylist-service/activities/search/activities``."""
        limit = max(1, min(limit, ACTIVITY_PAGE_MAX))
        params = [("start", str(start)), ("limit", str(limit)), *activity_filter_params(filters)]
        result = await self._request("/activitylist-service/activities/search/activities", params)
        if not result:
            return []
        if not isinstance(result, list):
            raise GarminApiError("activity search: unexpected response shape")
        return result

    async def search_activities(
        self, *, limit: int = ACTIVITY_PAGE_DEFAULT, filters: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Search activities, paging automatically up to ``limit`` results."""
        limit = max(1, min(limit, ACTIVITY_SEARCH_MAX_TOTAL))
        activities: list[dict[str, Any]] = []
        while len(activities) < limit:
            page_limit = min(ACTIVITY_PAGE_MAX, limit - len(activities))
            page = await self.search_activities_page(len(activities), page_limit, filters)
            activities.extend(page)
            if len(page) < page_limit:
                break
        return activities[:limit]

    async def get_activity(self, activity_id: int) -> Any:
        """``/activity-service/activity/{activityId}``."""
        return await self._request(f"/activity-service/activity/{_positive(activity_id)}")

    async def get_activity_workouts(self, activity_id: int) -> Any:
        """``/activity-service/activity/{activityId}/workouts``."""
        return await self._request(
            f"/activity-service/activity/{_positive(activity_id)}/workouts"
        )

    async def download_activity_zip(self, activity_id: int) -> bytes:
        """``/download-service/files/activity/{activityId}`` (ZIP archive)."""
        data = await self._request(
            f"/download-service/files/activity/{_positive(activity_id)}",
            accept=ZIP,
            binary=True,
        )
        if not data:
            raise GarminApiError("The activity download was empty")
        return data

    # -- health and wellness ----------------------------------------------

    async def get_hr_zones(self, *, generate_defaults: bool = False) -> Any:
        """``/biometric-service/heartRateZones/v2``."""
        return await self._request(
            "/biometric-service/heartRateZones/v2",
            [("generateDefaults", "true" if generate_defaults else "false")],
        )

    async def get_fitness_age(self, day: date, *, full_history_scan: bool = False) -> Any:
        """``/fitnessage-service/fitnessage/v2/{calendarDate}``."""
        return await self._request(
            f"/fitnessage-service/fitnessage/v2/{day.isoformat()}",
            [("fullHistoryScan", "true" if full_history_scan else "false")],
        )

    async def get_weight_goals(self, start: date, end: date) -> Any:
        """``/goal-service/goal/user/effective/weightgoal/{start}/{end}``."""
        return await self._request(
            f"/goal-service/goal/user/effective/weightgoal/{start.isoformat()}/{end.isoformat()}"
        )

    async def get_hrv(self, day: date) -> Any:
        """``/hrv-service/hrv/{calendarDate}`` (``None`` when there is no data)."""
        return await self._request(f"/hrv-service/hrv/{day.isoformat()}")

    async def get_hrv_summaries(self, start: date, end: date) -> list[dict[str, Any]]:
        """``/hrv-service/hrv/daily/{from}/{to}``, unwrapped to the summary list."""

        async def fetch(a: date, b: date) -> Any:
            page = _mapping_or_none(
                await self._request(f"/hrv-service/hrv/daily/{a.isoformat()}/{b.isoformat()}"),
                "hrv summaries",
            )
            return _list_field(page, "hrvSummaries", "hrv summaries") if page else []

        return await self._ranged(fetch, start, end, MAX_DAYS_HRV)

    async def get_food_logs(
        self,
        day: date,
        *,
        include_goals: bool = True,
        include_nutrition: bool = True,
        include_media: bool = False,
        meal_id: int | None = None,
    ) -> Any:
        """``/nutrition-service/food/logs/{date}``."""
        params = [
            ("includeGoals", "true" if include_goals else "false"),
            ("includeNutrition", "true" if include_nutrition else "false"),
            ("includeMedia", "true" if include_media else "false"),
        ]
        if meal_id is not None:
            params.append(("mealId", str(meal_id)))
        return await self._request(f"/nutrition-service/food/logs/{day.isoformat()}", params)

    async def get_menstrual_summary(self, day: date) -> Any:
        """``/periodichealth-service/menstrualcycle/summary/{calendarDate}``."""
        return await self._request(
            f"/periodichealth-service/menstrualcycle/summary/{day.isoformat()}"
        )

    async def get_menstrual_day_view(
        self,
        day: date,
        *,
        today: date | None = None,
        reduced_response: bool = False,
        include_analysis: bool = True,
        skip_baby_movement: bool = True,
    ) -> Any:
        """``/periodichealth-service/menstrualcycle/dayview/{calendarDate}``."""
        params: list[tuple[str, str]] = []
        if today is not None:
            params.append(("todayDate", today.isoformat()))
        params += [
            ("reducedResponse", "true" if reduced_response else "false"),
            ("skipbm", "true" if skip_baby_movement else "false"),
            ("includeAnalysis", "true" if include_analysis else "false"),
        ]
        return await self._request(
            f"/periodichealth-service/menstrualcycle/dayview/{day.isoformat()}", params
        )

    async def get_daily_sleep(self, day: date) -> Any:
        """``/sleep-service/sleep/dailySleep``."""
        return await self._request("/sleep-service/sleep/dailySleep", [("date", day.isoformat())])

    async def get_sleep_summaries(self, start: date, end: date) -> list[dict[str, Any]]:
        """``/sleep-service/sleep/dailySleepSummariesByDate`` (windows of 31 days)."""

        async def fetch(a: date, b: date) -> Any:
            return await self._request(
                "/sleep-service/sleep/dailySleepSummariesByDate",
                [("startDate", a.isoformat()), ("endDate", b.isoformat())],
            )

        return await self._ranged(fetch, start, end, MAX_DAYS_SLEEP)

    async def get_profile_settings(self) -> Any:
        """``/userprofile-service/userprofile/settings``."""
        return await self._request("/userprofile-service/userprofile/settings")

    async def get_hydration(self, start: date, end: date) -> list[dict[str, Any]]:
        """``/usersummary-service/stats/hydration/daily/{start}/{end}``."""

        async def fetch(a: date, b: date) -> Any:
            return await self._request(
                f"/usersummary-service/stats/hydration/daily/{a.isoformat()}/{b.isoformat()}"
            )

        return await self._ranged(fetch, start, end, MAX_DAYS_HYDRATION)

    async def get_steps(self, start: date, end: date) -> list[dict[str, Any]]:
        """``/usersummary-service/stats/steps/daily/{start}/{end}``."""

        async def fetch(a: date, b: date) -> Any:
            return await self._request(
                f"/usersummary-service/stats/steps/daily/{a.isoformat()}/{b.isoformat()}"
            )

        return await self._ranged(fetch, start, end, MAX_DAYS_STEPS)

    async def get_stress(self, start: date, end: date) -> list[dict[str, Any]]:
        """``/usersummary-service/stats/stress/daily/{start}/{end}``."""

        async def fetch(a: date, b: date) -> Any:
            return await self._request(
                f"/usersummary-service/stats/stress/daily/{a.isoformat()}/{b.isoformat()}"
            )

        return await self._ranged(fetch, start, end, MAX_DAYS_STRESS)

    async def get_daily_summary(self, day: date) -> Any:
        """``/usersummary-service/usersummary/daily``."""
        return await self._request(
            "/usersummary-service/usersummary/daily", [("calendarDate", day.isoformat())]
        )

    async def get_daily_summaries(self, start: date, end: date) -> list[dict[str, Any]]:
        """``/usersummary-service/v2/dailysummaries``, unwrapped (windows of 31 days)."""

        async def fetch(a: date, b: date) -> Any:
            page = _mapping_or_none(
                await self._request(
                    "/usersummary-service/v2/dailysummaries",
                    [("startDate", a.isoformat()), ("endDate", b.isoformat())],
                ),
                "daily summaries",
            )
            return _list_field(page, "data", "daily summaries") if page else []

        return await self._ranged(fetch, start, end, MAX_DAYS_DAILY_SUMMARIES)

    async def get_weights_all(self, start: date, end: date) -> Any:
        """``/weight-service/weight/all/{start}/{end}``.

        Garmin currently answers HTTP 400 for every input; kept for completeness.
        """
        return await self._request(
            f"/weight-service/weight/all/{start.isoformat()}/{end.isoformat()}"
        )

    async def get_weight_range(
        self, start: date, end: date, *, include_all: bool = True
    ) -> dict[str, Any]:
        """``/weight-service/weight/range/{start}/{end}`` merged over windows."""
        merged: dict[str, Any] = {"dailyWeightSummaries": []}
        for window_start, window_end in split_range(start, end, MAX_DAYS_WEIGHT):
            page = _mapping_or_none(
                await self._request(
                    f"/weight-service/weight/range/{window_start.isoformat()}"
                    f"/{window_end.isoformat()}",
                    [("includeAll", "true" if include_all else "false")],
                ),
                "weight range",
            )
            if not page:
                continue
            merged["dailyWeightSummaries"].extend(
                _list_field(page, "dailyWeightSummaries", "weight range")
            )
            for key in ("totalAverage", "previousDateWeight", "nextDateWeight"):
                if page.get(key) is not None:
                    merged[key] = page[key]
        return merged

    async def get_body_battery(
        self, start: date, end: date, *, chunks: int | None = None
    ) -> list[Any]:
        """``/wellness-service/wellness/bodyBattery/reports/daily``."""

        async def fetch(a: date, b: date) -> Any:
            params = [("startDate", a.isoformat()), ("endDate", b.isoformat())]
            if chunks is not None:
                params.append(("chunks", str(chunks)))
            return await self._request(
                "/wellness-service/wellness/bodyBattery/reports/daily", params
            )

        return await self._ranged(fetch, start, end, MAX_DAYS_BODY_BATTERY)

    async def get_spo2(self, day: date) -> Any:
        """``/wellness-service/wellness/daily/spo2acclimation/{calendarDate}``."""
        return await self._request(
            f"/wellness-service/wellness/daily/spo2acclimation/{day.isoformat()}"
        )

    async def get_heart_rate(self, day: date) -> Any:
        """``/wellness-service/wellness/dailyHeartRate``."""
        return await self._request(
            "/wellness-service/wellness/dailyHeartRate", [("date", day.isoformat())]
        )

    async def get_wellness_activities(self, start: date, end: date) -> list[Any]:
        """``/wellnessactivity-service/activity/summary/range/{from}/{until}``."""

        async def fetch(a: date, b: date) -> Any:
            return await self._request(
                f"/wellnessactivity-service/activity/summary/range/{a.isoformat()}/{b.isoformat()}"
            )

        return await self._ranged(fetch, start, end, MAX_DAYS_WELLNESS_ACTIVITIES)

    # -- generic dispatch for the ``fetch`` service ------------------------

    async def fetch(
        self,
        endpoint: str,
        *,
        today: date | None = None,
        day: date | None = None,
        start: date | None = None,
        end: date | None = None,
        activity_id: int | None = None,
        filters: Mapping[str, Any] | None = None,
        limit: int = ACTIVITY_PAGE_DEFAULT,
    ) -> Any:
        """Call one of the endpoints by its short name (see ``ENDPOINT_NAMES``).

        ``today`` is the current day in the Home Assistant time zone, supplied by the
        caller. Only if it is missing, the process-local date is used as a fallback.
        """
        today = today or date.today()
        day = day or today
        end = end or day
        start = start or (end - timedelta(days=6))
        if endpoint not in ENDPOINT_NAMES:
            raise ValueError(f"unknown endpoint: {endpoint}")
        match endpoint:
            case "activities":
                return await self.search_activities(limit=limit, filters=filters)
            case "activity":
                return await self.get_activity(_need_id(activity_id))
            case "activity_workouts":
                return await self.get_activity_workouts(_need_id(activity_id))
            case "hr_zones":
                return await self.get_hr_zones()
            case "fitness_age":
                return await self.get_fitness_age(day)
            case "weight_goals":
                return await self.get_weight_goals(start, end)
            case "hrv":
                return await self.get_hrv(day)
            case "hrv_summaries":
                return await self.get_hrv_summaries(start, end)
            case "nutrition":
                return await self.get_food_logs(day)
            case "menstrual_summary":
                return await self.get_menstrual_summary(day)
            case "menstrual_day":
                return await self.get_menstrual_day_view(day, today=today)
            case "sleep":
                return await self.get_daily_sleep(day)
            case "sleep_summaries":
                return await self.get_sleep_summaries(start, end)
            case "profile":
                return await self.get_profile_settings()
            case "hydration":
                return await self.get_hydration(start, end)
            case "steps":
                return await self.get_steps(start, end)
            case "stress":
                return await self.get_stress(start, end)
            case "daily_summary":
                return await self.get_daily_summary(day)
            case "daily_summaries":
                return await self.get_daily_summaries(start, end)
            case "weights_all":
                return await self.get_weights_all(start, end)
            case "weight_range":
                return await self.get_weight_range(start, end)
            case "body_battery":
                return await self.get_body_battery(start, end)
            case "spo2":
                return await self.get_spo2(day)
            case "heart_rate":
                return await self.get_heart_rate(day)
            case "wellness_activities":
                return await self.get_wellness_activities(start, end)
        raise ValueError(f"unknown endpoint: {endpoint}")  # pragma: no cover


# Short names accepted by the ``fetch`` service: 25 data endpoints. The 26th,
# the activity file download, has its own service.
ENDPOINT_NAMES: tuple[str, ...] = (
    "activities",
    "activity",
    "activity_workouts",
    "hr_zones",
    "fitness_age",
    "weight_goals",
    "hrv",
    "hrv_summaries",
    "nutrition",
    "menstrual_summary",
    "menstrual_day",
    "sleep",
    "sleep_summaries",
    "profile",
    "hydration",
    "steps",
    "stress",
    "daily_summary",
    "daily_summaries",
    "weights_all",
    "weight_range",
    "body_battery",
    "spo2",
    "heart_rate",
    "wellness_activities",
)


def _positive(activity_id: int) -> int:
    if isinstance(activity_id, bool) or not isinstance(activity_id, int) or activity_id <= 0:
        raise ValueError("activity_id must be a positive integer")
    return activity_id


def _need_id(activity_id: int | None) -> int:
    if activity_id is None:
        raise ValueError("this endpoint needs an activity_id")
    return activity_id
