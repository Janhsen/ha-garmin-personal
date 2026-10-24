# Garmin Connect Personal API for Home Assistant

*[Deutsche Fassung](README.de.md)*

Custom integration (HACS) exposing **all 26 read endpoints** of the official Garmin Connect Personal API:
sensors for the common values and services for everything else. Nothing is calculated or invented:
what Garmin does not deliver stays empty (`unknown`).

> **Status:** running against a real Garmin account in Home Assistant (current version: see `manifest.json` and the
> [changelog](CHANGELOG.md)). Tokens, retries, time windows, filters, value extraction and the sensor list are tested
> with simulated responses. Field names come from the Swagger file, the documented models and real responses.
> Please report sensors that stay empty permanently, with the diagnostics and the log.

## Installation

1. HACS → Custom repositories → add this repository as *Integration*.
2. Download it and restart Home Assistant.
3. Create a key at <https://connect.garmin.com/app/settings/personalApiToken>
   (Garmin shows it **only once**) and note the validity you chose.
4. Settings → Devices & services → Add integration → *Garmin Connect Personal API*.
   Create one entry per person, each with its own key.

The key is stored only in Home Assistant. Do not enter it anywhere else. A name is required (there is no default);
it becomes the device name and part of the entity IDs. The account is recognised by Garmin's internal profile ID, so
renaming the account or changing the Garmin display name does not matter; entries created by an earlier version are
switched over automatically at the first start after the update, entities and history stay. Home Assistant 2025.10.0
or newer is required.

## What you see after setup

* One **device** per account, named like the account (for example "Alex"), with about 120 sensors, a binary sensor,
  an event entity and a calendar. About half of the sensors are **enabled by default**; the rest are detail values
  you can switch on under Settings → Entities.
* Entity IDs follow the device name and the sensor name in the language Home Assistant used when the entity was
  created, for example `sensor.alex_steps` (English) or `sensor.alex_schritte` (German). Look them up under
  Settings → Entities; the examples below use these names.
* Values appear after the first fetch. Some sensors stay empty until Garmin has something to deliver (sleep early in
  the morning, body values without a scale). Shortly after the first full fetch, sensors for which Garmin returns
  no value at all are disabled once (see below).
* The live sensors have **no history before the moment they were created**. To get older days into charts, run
  `garmin_personal.backfill_statistics` once (see "History and long-term statistics").

## Two people (one entry per person)

Add the integration once per person, each with that person's own key and a different name ("Alex", "Sam").
Every entry has its own device, sensors, event and calendar, so entity names carry the person's name. Services act
on **one** account: with several accounts you must choose it in the *Account* field (see the example under
Services). Keys expire independently; each entry has its own "API key expires" sensor and repair notice.

## Key expiry

Garmin does not reveal the expiry date through the API. The date shown is therefore **calculated**, not read from
Garmin: the integration counts from the moment you add the key with the validity you picked (30/90/180/365 days).
Pick the same validity you chose at Garmin, otherwise the date is wrong and the warning comes too late or too early.
A diagnostic sensor "API key expires" shows the calculated date (it works locally and does not depend on the connection
to Garmin). A repair issue appears **7 days before** (checked hourly) and turns into an error after the date. To renew: create a new key, then *Reconfigure* the entry. If Garmin rejects the key earlier, Home Assistant starts
re-authentication automatically.

## Sensors (~120)

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
alone. This happens only for body and activity sensors, only once the entry is at least 24 hours old and the watch
has synced on the same day; the keys are written to the log at info level. You can re-enable any sensor under
Settings → Entities. Also included: binary sensor *Watch sync overdue*
and the event entity *Activity*.

**The event fires after the watch has synced**, when Garmin Connect lists a new activity (event type
`activity_finished`), not at the moment the workout ends; between the two can be hours. Activities
that appeared while Home Assistant was restarting are reported after the start. For a new account nothing is
reported at the first fetch, and an empty first answer from Garmin sets no starting point. The event data (attributes of the event entity) hold
`activity_id`, `name`, `type`, `start_time_gmt`, `distance` (meters), `duration` (seconds) and `calories`.

In addition: a **calendar** entity with the latest activities (about 20, from Garmin's start time and the elapsed duration if
Garmin delivers it; distance in your unit system, calories and average heart rate in the description; the entity
shows only a running or the next upcoming activity as its current event), disabled-by-default sensors for stress shares,
average altitude, highest/lowest respiration, lowest/highest average heart rate, the Body Battery level with Garmin's
feedback and event list as attributes, and the sleep alignment with Garmin's recommended window (minutes after
midnight, as delivered).

Options: update interval for the daily values (this is the sync check), sync warning threshold, and whether intraday
series (heart rate, Body Battery, SpO2) are attached as attributes (large, not stored in the recorder). Only with this
option are the extra endpoints for heart rate and Body Battery series requested for the sensors.

The option **Write hourly statistics** (on by default) is independent of that: after each new watch sync it writes
heart rate, Body Battery and SpO2 as hourly values into the long-term statistics (see "History and long-term
statistics"). It reuses the requests that run anyway and otherwise asks once more per series.

Units: distances are in meters and durations in seconds (sleep need in minutes); the unit is shown on each sensor,
and a dashboard card can convert it. Many "today" values (steps, minimum/maximum heart rate) start again at midnight.

Request volume: about 290 requests per day and account for the sync check, plus about 9 per watch sync and the
fallbacks, roughly 400 to 500 in total (without intraday series). Hourly statistics add about 2 requests per watch
sync (heart rate and Body Battery of today; SpO2 is already requested) and 3 for yesterday on the first full refresh
of each day and after each sync before 10:00 local time, so roughly 30 to 60 more per day. With the intraday
attributes on, today's series are requested anyway and only yesterday's 3 remain. Garmin names no limits for the
Personal API and offers no push; the integration only polls.

Not part of the Personal API (and therefore not available): Training Readiness, training status, VO2max as a daily
value, race predictions. VO2max exists only per activity.

Sleep, HRV and body sensors keep their **last known value** while Garmin returns nothing (e.g. the next morning
before the new night is synced), also across restarts. The attributes `held_value` (true while the value is old)
and `last_seen` (when this value first arrived here, not when it was measured) say so. Nothing is estimated. In
long-term statistics a held value continues as a flat line; use `backfill_statistics` for exact daily values. If Garmin
cannot be reached for a short time, all sensors keep their last values (never across midnight for daily values); after
about 15 minutes (or three update intervals) without a successful update they become unavailable. Zero, negative and
placeholder values that Garmin sends for "not measured" (for example a weight of 0 or a night of 0 seconds) are
treated as no value. The weight sensors ignore entries that are only a profile change.

## Examples

Notification after a new activity:

```yaml
alias: Garmin activity message
triggers:
  - trigger: state
    entity_id: event.alex_activity
actions:
  - action: notify.notify
    data:
      message: >-
        New activity: {{ trigger.to_state.attributes.name }},
        {{ (trigger.to_state.attributes.distance / 1000) | round(1) }} km
```

Warning when the watch has not synced for a while: use the binary sensor *Watch sync overdue*
(`binary_sensor.alex_watch_sync_overdue`) as the trigger; the threshold is set in the options.

Dashboard: a *Statistics graph* card or a plain entities card with `sensor.alex_steps`, `sensor.alex_sleep_score`
and `sensor.alex_resting_heart_rate` shows the main values.

## Services (responses as data, e.g. for scripts and templates)

With **several accounts** every service needs the *Account* field. In the form you pick it from a list; in YAML it is
the config entry ID (open the service form, pick the account, switch to YAML mode and copy the value). Example with a
response:

```yaml
action: garmin_personal.fetch
data:
  config_entry_id: <entry_id>
  endpoint: sleep
  date: "2026-01-15"
response_variable: result
```

With exactly one account the field may be left out. If it is missing and several accounts exist, the service stops
with a translated error that lists the accounts. All service errors are translated.

* `garmin_personal.fetch` – any endpoint by short name (`daily_summary`, `sleep`, `hrv_summaries`, `stress`,
  `menstrual_summary`, `nutrition`, `activity`, …) for a day or a range. Long ranges are split into the windows
  Garmin allows.
* `garmin_personal.search_activities` – filters such as `activity_type`, `min_distance`, `start_date`,
  `bounding_box`, with automatic paging.
* `garmin_personal.download_activity` – original ZIP (FIT) into a folder that Home Assistant allows
  (`allowlist_external_dirs`); default `<media folder>/garmin_personal/activity_<id>.zip`. Only `.zip` targets are
  accepted, and a folder as the path gets the default file name appended; otherwise the service reports that the
  path is not allowed.
* `garmin_personal.backfill_statistics` – writes daily values retroactively into **long-term statistics**
  (external statistic `garmin_personal:<entry>_<name>`, one value per day): activity (steps, heart rate, stress,
  Body Battery, calories …), sleep (duration, stages, score, heart rate, sleep need), HRV and weight/body values.
  Only real Garmin days are imported: days from other sources and pure placeholder days without steps and heart
  rate are skipped, as are weight entries that are only a profile edit. With `include_third_party_steps`, steps,
  distance and floors of days written to Garmin Connect by other apps (e.g. RunGap) are imported too. Repeatable;
  it overwrites the same days. Without `end_date` the import ends yesterday (today only if you give it explicitly,
  because today is incomplete); at most 3650 days; it runs in 31-day windows and only one import per account at a
  time. The response reports `complete`, `last_completed_day` and `error` after an interruption, plus
  `days_imported`, `statistic_series` and `statistic_rows`. Days with a value of 0 for resting/minimum/maximum heart
  rate, stress or respiration are not written.
* `garmin_personal.backfill_intraday` – writes the day curves of **heart rate, Body Battery and SpO2** retroactively as
  **hourly statistics** (minimum, maximum and mean per full hour, see "History and long-term statistics"). `days`
  (default 7), `start_date` and `end_date` work as above; without `end_date` it ends today (only completed hours are
  written, never the running one), at most 366 days. One request per day and series (3 per day, so a year is about
  1100 requests: run long ranges in pieces if Garmin answers with a rate limit). Repeatable; the same hours are
  overwritten. Only one import per account at a time (shared with `backfill_statistics`). The response reports
  `complete`, `last_completed_day` and `error` after an interruption, plus `heart_rate_hours`, `body_battery_hours`,
  `spo2_hours`, `days_with_data`, `statistic_series` and `statistic_rows`; `unknown_format` lists series whose
  answer this version cannot read.
* `garmin_personal.backfill_history` – **scaffold, not active yet.** Meant to write the real measuring points of heart
  rate, Body Battery and SpO2 with their own timestamps as recorded states of the disabled-by-default diagnostic
  sensors *Heart rate (history)*, *Body Battery (history)* and *SpO2 (history)* (the live sensors never get old values),
  so that the History panel shows them. It is append-only: a persistent record per series and day (exact timestamps and
  values for the last 7 days, count/first/last/checksum for older days) decides "written already?", never just a last
  timestamp; late-synced older points are added, already written points are never rewritten, overwritten or deleted,
  and a changed value for a known timestamp is only counted (`changed_values_skipped`). If the record is lost, the
  recorder is read first; without that check nothing is written unless `confirm_rewrite` is true. Because Home Assistant
  has no supported way to store states with past timestamps, the service currently answers `history_write_unsupported`
  before asking Garmin for anything. The sensors exist (disabled) and show no value.

## Translations

All names, services, dialogs and notices are available in English and German (`strings.json`, `translations/`,
generated with `scripts/gen_translations.py`). Fixed word lists from Garmin (rating EXCELLENT/GOOD/FAIR/POOR, HRV
status, stress level, activity type, sleep sub-scores, sleep feedback and insight) are ENUM sensors: the state
stays the English key (e.g. `fair`) and Home Assistant shows the translation. Sleep sub-scores, sleep feedback, insight and
the personal insight are translated literally from the key, only for keys seen in real responses. Unknown values are
shown untranslated, logged once at info level (enable it with `custom_components.garmin_personal: info` under
`logger:` in `configuration.yaml`), and never hidden. HRV feedback (`HRV_BALANCED_2` to `_8`,
`ONBOARDING_1`) is shown as "Balanced: 6" / "Ausgeglichen: 6": these are numbered text variants of Garmin's app
whose wording the API does not provide, so only the number is shown, not a meaning or a scale. The stress level has no
"unknown" state: Garmin's `UNKNOWN` is shown as Home Assistant's own empty state. The sensor *Breathing disruption*
has no word list yet because the values Garmin sends are not known; each value seen is shown as it is and logged once.

## History and long-term statistics

* Live sensors appear in the History panel only from the moment they were created.
* Retroactively imported daily values (`backfill_statistics`) are external statistics with their own name
  (the account name followed by the value name) and are **separate from the live sensors**: a card for
  `sensor.alex_steps` does not show imported days. The History panel does not show them either; use a
  *Statistics graph* card and pick the imported statistic, or look under Developer tools → Statistics
  (search for `garmin_personal`). The statistic ID is `garmin_personal:<entry_id>_<name>`, the display name is the
  account name followed by the English value name. A few names differ from the sensor keys (`sleep_respiration`,
  `hrv_weekly_average`, `hrv_5_min_high`):

  ```yaml
  type: statistics-graph
  entities:
    - garmin_personal:<entry_id>_steps
  period: day
  stat_types:
    - mean
  ```
* Each imported day is stored as one value at the first hour of that day. With the period *hour*, a card therefore
  shows a spike at midnight and gaps otherwise; use the period *day*.
* **Hourly values** (heart rate, Body Battery, SpO2) are separate statistics with one value per full hour: minimum,
  maximum and mean of the real Garmin measurements in that hour (the mean is the plain mean of the points, not
  weighted by time). They are written after each new watch sync (option *Write hourly statistics*) and retroactively
  with `backfill_intraday`. IDs: `garmin_personal:<entry_id>_heart_rate_hourly`, `…_body_battery_hourly`,
  `…_spo2_hourly` (units bpm, %, %). Only completed hours are stored, never the running one; the hours of today and
  yesterday are recalculated and overwritten after each sync, so later corrections by Garmin are taken over. Hours
  without a measurement stay empty: nothing is interpolated or filled, and placeholder values (0 or negative for heart
  rate and SpO2, negative for Body Battery) are dropped. Hours are full UTC hours. Heart rate has about one point every
  two minutes, so an hour has up to 30 points; Garmin's SpO2 answer only holds hourly averages, so minimum, maximum and
  mean of an SpO2 hour are the same. Where to see them: a *Statistics graph* card (pick the statistic, period *hour*
  or *day*, `stat_types` `min`, `max`, `mean`) or Developer tools → Statistics. They do **not** appear in the History
  panel, which only shows states of entities; they are not states, so they are not stored there or in the attributes.
  In time zones whose offset is not a whole number of hours, the hour around local midnight is left out at the edge
  of a fetched range instead of being stored from half its measurements.

  ```yaml
  type: statistics-graph
  entities:
    - garmin_personal:<entry_id>_heart_rate_hourly
  period: hour
  stat_types:
    - min
    - mean
    - max
  ```

## Spotting Garmin API changes

`docs/api-fields/` holds the key paths (names only, no values) of known Garmin responses. `scripts/api_fields.py --diff`
compares a fresh response with them and lists new (+) and removed (-) fields, so additions or changes on Garmin's side
become visible instead of silently missing.

## Privacy

Health data. Menstrual and nutrition data are available **only** through services on explicit request, never as
sensors. Diagnostics contain neither the key nor measurements (nor the account ID or name). The sensor *Last
activity* carries the start coordinates, place name and description of the activity as attributes; they are visible live
and in cards that display attributes, but excluded from the recorder (like the series attributes). Keep this in mind
when sharing dashboards. Service responses can contain personal data as well (they also appear in automation traces);
do not post them publicly. `download_activity` writes into the media folder by default; files there are not served
without login, unlike the `www` folder.

## Garmin quirks that are handled

Range limits (steps/stress 28 days, sleep/hydration/Body Battery 31 days, HRV 365 days), about 45 activities per
page, retry on 429/5xx honouring `Retry-After`, a new token exchange on 401, timestamps as ISO or milliseconds.
`weight/all` currently always returns HTTP 400 at Garmin and is reachable via `fetch` only for completeness.

## Troubleshooting

* **A sensor stays `unknown`.** Garmin does not deliver the field (for example body fat without a body-composition
  scale), or the sensor is a detail sensor that was disabled once at the first fetch. Enable it under Settings →
  Entities. The diagnostics of the integration show which fields Garmin returned.
* **Sleep or HRV is empty in the morning.** The night is available only after the watch has synced. Until then the
  sensor keeps yesterday's value; the attribute `held_value` is then true.
* **"The key was rejected" / re-authentication.** The key expired or was revoked. Create a new one at Garmin, in the
  same Garmin account, and use *Reconfigure* (see "Key expiry").
* **Rate limit or short outages.** After HTTP 429 or a failed token exchange the integration pauses requests for a
  while (honouring `Retry-After`) and keeps the last values meanwhile.
* **Sync overdue.** The watch has not synced with the Garmin app for longer than the configured hours; the values stay
  as they are until it syncs.
* **More detail in the log.** Add `custom_components.garmin_personal: debug` under `logger:` → `logs:`.

## Removal

Delete the entry under Settings → Devices & services. This also removes the repair issue and the internal marker for
the last seen activity. The key stays valid at Garmin until it expires; revoke it in
Garmin Connect if you no longer need it. Statistics imported with `backfill_statistics` stay in the database; remove
them with the service `recorder.clear_statistics` and their statistic IDs.

## Development

```
for f in tests/test_*.py; do python3 -I $f || echo FAIL $f; done
python3 -I scripts/gen_translations.py          # generates strings.json, translations/ and icons.json
python3 -I scripts/gen_translations.py --check  # fails if the generated files are out of date
ruff check .
```
CI (`.github/workflows`) runs the tests, `ruff` and hassfest; a release is only built after they pass.
Start each test file in its own process (the Home Assistant stubs replace modules in `sys.modules`). The tests need
neither Home Assistant nor network access. Never edit `strings.json`, `translations/` or `icons.json` by hand; names,
word lists and texts live in `scripts/gen_translations.py` and `custom_components/garmin_personal/labels.py`.

Personal use according to Garmin's terms for the Personal API.
