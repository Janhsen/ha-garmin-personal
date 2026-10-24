"""Constants for the Garmin Personal API integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "garmin_personal"

DEFAULT_BASE_URL: Final = "https://personal.connectapi.garmin.com"
KEY_EXCHANGE_PATH: Final = "/personalapitoken-service/personal-api/personal-api-key/token"

# Config entry data
CONF_API_KEY: Final = "api_key"
CONF_KEY_VALIDITY: Final = "key_validity_days"
CONF_KEY_EXPIRES: Final = "key_expires_at"
CONF_PRUNED: Final = "initial_prune_done"

# Options
OPT_DAILY_INTERVAL: Final = "daily_interval_minutes"
OPT_INTRADAY: Final = "intraday_attributes"
OPT_SYNC_STALE_HOURS: Final = "sync_stale_hours"

DEFAULT_DAILY_INTERVAL: Final = 15
DEFAULT_SLEEP_INTERVAL: Final = 60
DEFAULT_BODY_INTERVAL: Final = 60
DEFAULT_ACTIVITY_INTERVAL: Final = 30
DEFAULT_PROFILE_INTERVAL: Final = 24 * 60
DEFAULT_SYNC_STALE_HOURS: Final = 12

KEY_VALIDITY_CHOICES: Final = ("30", "90", "180", "365")
KEY_EXPIRY_WARNING: Final = timedelta(days=7)

# Garmin's documented and observed limits (inclusive days per request).
# Larger ranges are split into windows by the client.
MAX_DAYS_STEPS: Final = 28
MAX_DAYS_STRESS: Final = 28
MAX_DAYS_HYDRATION: Final = 31
MAX_DAYS_BODY_BATTERY: Final = 31
MAX_DAYS_SLEEP: Final = 31
MAX_DAYS_DAILY_SUMMARIES: Final = 31
MAX_DAYS_HRV: Final = 365
MAX_DAYS_WEIGHT: Final = 360
MAX_DAYS_WELLNESS_ACTIVITIES: Final = 31

# The activity search fails with HTTP 500 above ~45 activities per page.
ACTIVITY_PAGE_MAX: Final = 45
ACTIVITY_PAGE_DEFAULT: Final = 20
ACTIVITY_SEARCH_MAX_TOTAL: Final = 500

# Refresh the 24 h access token shortly before it expires.
TOKEN_REFRESH_MARGIN: Final = timedelta(minutes=5)
FALLBACK_TOKEN_LIFETIME: Final = timedelta(hours=24)

RETRY_STATUSES: Final = frozenset({408, 429, 500, 502, 503, 504})
MAX_RETRIES: Final = 2
MAX_RETRY_AFTER: Final = 60.0

# Services
SERVICE_FETCH: Final = "fetch"
SERVICE_SEARCH_ACTIVITIES: Final = "search_activities"
SERVICE_DOWNLOAD_ACTIVITY: Final = "download_activity"
SERVICE_BACKFILL: Final = "backfill_statistics"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"

EVENT_ACTIVITY_FINISHED: Final = "activity_finished"
