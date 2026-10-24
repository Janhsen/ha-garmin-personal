# Garmin Connect Personal API for Home Assistant

*[Deutsche Fassung](README.de.md)*

Custom integration (HACS) exposing **all 26 read endpoints** of the official Garmin Connect Personal API:
sensors for the common values and services for everything else. Nothing is calculated or invented:
what Garmin does not deliver stays empty (`unknown`).

> **Status:** v0.3.5, running against a real Garmin account in Home Assistant. Tokens, retries, time windows,
> filters, value extraction and the sensor list are tested with simulated responses. Field names come from the
> Swagger file, the documented models and real responses. Please report sensors that stay empty permanently,
> with the diagnostics and the log.

## Installation

1. HACS → Custom repositories → add this repository as *Integration*.
2. Download it and restart Home Assistant.
3. Create a key at <https://connect.garmin.com/app/settings/personalApiToken>
   (Garmin shows it **only once**) and note the validity you chose.
4. Settings → Devices & services → Add integration → *Garmin Connect Personal API*.
   Create one entry per person, each with its own key.

The key is stored only in Home Assistant. Do not enter it anywhere else.

## Key expiry

Garmin does not reveal the expiry date through the API. The integration counts from the moment you add the key
with the validity you picked (30/90/180/365 days), shows a diagnostic sensor "API key expires" and creates a
repair issue **7 days before**. To renew: create a new key, then *Reconfigure* the entry. If Garmin rejects the key
earlier, Home Assistant starts re-authentication automatically.

## Sensors (~100)

Polling: the daily summary (which carries the time of the last watch sync) is requested every 5 minutes, a single
request. Only when the sync time changes are SpO2, hydration, sleep, body values and activities fetched. A
fallback covers data that appears without a watch sync, e.g. a scale or app entries (daily values hourly, sleep
every 2 hours, body values and activities hourly).

| Group | Content |
|---|---|
| Daily values (summary 5 min, the rest on new sync / hourly) | steps, distance, calories, intensity minutes, floors, heart rate (rest/min/max), stress, Body Battery, SpO2, respiration, hydration, last sync |
| Sleep & HRV (on new sync, otherwise 2 h) | duration, stages, sleep score and sub-scores, start/end, sleep need, HRV last night/week/status |
| Body (on new sync, otherwise 1 h) | weight, BMI, body fat/water, muscle/bone mass, fitness age |
| Activities (on new sync, otherwise 1 h) | last activity (name, type, start, distance, duration, calories, heart rate, training effect, load, VO2max, elevation), wellness activities |
| Profile (24 h) | account, configured heart rate zones |

Many detail sensors are **disabled by default** and can be enabled one by one. After the first full fetch, sensors
for which Garmin answers the endpoint but returns no value for the field (e.g. body fat without a body-composition
scale) are disabled once. Endpoints that have not delivered anything yet (e.g. sleep early in the morning) are left
alone. You can re-enable any sensor under Settings → Entities. Also included: binary sensor *Watch sync overdue*
and the event entity *Activity* (fires `activity_finished` for every new activity, not on first start).

Options: sync check interval, sync warning threshold, and whether intraday series (heart rate, Body Battery, SpO2)
are attached as attributes (large, not stored in the recorder). Only with this option are the extra endpoints for
heart rate and Body Battery series requested.

Request volume: about 290 requests per day and account for the sync check, plus about 9 per watch sync and the
fallbacks, roughly 400 to 500 in total (without intraday series). Garmin names no limits for the Personal API and
offers no push; the integration only polls.

Not part of the Personal API (and therefore not available): Training Readiness, training status, VO2max as a daily
value, race predictions. VO2max exists only per activity.

## Services (responses as data, e.g. for scripts and templates)

* `garmin_personal.fetch` – any endpoint by short name (`daily_summary`, `sleep`, `hrv_summaries`, `stress`,
  `menstrual_summary`, `nutrition`, `activity`, …) for a day or a range. Long ranges are split into the windows
  Garmin allows.
* `garmin_personal.search_activities` – filters such as `activity_type`, `min_distance`, `start_date`,
  `bounding_box`, with automatic paging.
* `garmin_personal.download_activity` – original ZIP (FIT) into an allowed folder.
* `garmin_personal.backfill_statistics` – writes daily values retroactively into **long-term statistics**
  (external statistic `garmin_personal:<entry>_<name>`, one value per day): activity (steps, heart rate, stress,
  Body Battery, calories …), sleep (duration, stages, score, heart rate, sleep need), HRV and weight/body values.
  Only real Garmin days are imported: days from other sources and pure placeholder days without steps and heart
  rate are skipped, as are weight entries that are only a profile edit. With `include_third_party_steps`, steps,
  distance and floors of days written to Garmin Connect by other apps (e.g. RunGap) are imported too. Repeatable;
  it overwrites the same days.

## Translations

All names, services, dialogs and notices are available in English and German (`strings.json`, `translations/`,
generated with `scripts/gen_translations.py`). Fixed word lists from Garmin (rating EXCELLENT/GOOD/FAIR/POOR, HRV
status, stress level, activity type, sleep sub-scores, sleep feedback and insight) are ENUM sensors: the state
stays the English key (e.g. `fair`) and Home Assistant shows the translation. Sleep feedback, insight and the
personal insight are translated literally from the key, only for keys seen in real responses. Unknown values are
shown untranslated, logged once at info level, and never hidden. HRV feedback (`HRV_BALANCED_2` to `_8`,
`ONBOARDING_1`) is shown as "Balanced: 6" / "Ausgeglichen: 6": these are numbered text variants of Garmin's app
whose wording the API does not provide, so only the number is shown, not a meaning or a scale.

## History and long-term statistics

* Live sensors appear in the History panel only from the moment they were created.
* Retroactively imported daily values (`backfill_statistics`) are external statistics. The History panel does not
  show them; use a *Statistics graph* card or Developer tools → Statistics.

## Privacy

Health data. Menstrual and nutrition data are available **only** through services on explicit request, never as
sensors. Diagnostics contain neither the key nor measurements.

## Garmin quirks that are handled

Range limits (steps/stress 28 days, sleep/hydration/Body Battery 31 days, HRV 365 days), about 45 activities per
page, retry on 429/5xx honouring `Retry-After`, a new token exchange on 401, timestamps as ISO or milliseconds.
`weight/all` currently always returns HTTP 400 at Garmin and is reachable via `fetch` only for completeness.

## Development

```
python3 -I tests/test_api.py && python3 -I tests/test_values.py && python3 -I tests/test_sensors.py
python3 -I scripts/gen_translations.py   # generates strings.json and translations/
```
The tests need neither Home Assistant nor network access.

Personal use according to Garmin's terms for the Personal API.
