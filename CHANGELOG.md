# Changelog

All notable changes to the Garmin Connect Personal API integration. Versions follow `manifest.json`;
each GitHub release shows the matching section.

## 0.5.8

### Added
- `garmin_personal.fetch` accepts the raw Garmin parameters `chunks` (Body Battery), `full_history_scan` (fitness age) and
  `include_all` (weight range), for reading tests. They are only sent when given; without them the request is the one the
  sensors send.
- Sensor *Heart rate alerts* (Garmin's count of abnormal heart rate alerts per day, disabled by default) with the high and
  low alert thresholds as attributes when the heart rate answer of the day is requested.
- Sensors *Last activity average speed* and *Last activity maximum speed* (disabled by default): Garmin's value in m/s, shown
  in km/h by default.
- *Last activity*: attributes `hrTimeInZone_1` to `_5` (seconds per heart rate zone) and `fastestSplit_1000`, `_1609`,
  `_5000`, `_10000`, `_21098`, `_42195` (seconds), when Garmin sends them.
- The fitness age sensor has Garmin's `previous_fitness_age` as an attribute.
- New statistics for `backfill_statistics` (new IDs only): `hydration`, `hydration_goal`, `spo2_average`, `spo2_lowest`,
  `respiration_lowest`, `respiration_highest`, `floors_descended`, `step_goal`, `stress_rest_time`, `stress_low_time`,
  `stress_medium_time`, `stress_high_time`, `sleep_spo2_average`, `sleep_spo2_lowest`, `sleep_respiration_lowest`,
  `sleep_respiration_highest`, `sleep_need_next`, `nap_duration`, `sleep_score_rem`, `sleep_score_light`,
  `sleep_score_deep`, `visceral_fat`, `metabolic_age`. A value Garmin does not send for a day is not written.
- The unit of *Last activity VO2max* is shown (ml/kg/min).
- Documentation: table of all endpoints with short name, largest range, entities and refresh (generated from the code), steps
  as a daily total only, 24-hour token without refresh token, key validity and Garmin's e-mail, list of what the API does not
  offer, units (weight: Garmin's specification says kilograms, real responses contain grams, the integration divides by 1000),
  differences between imported days and live sensors, the fitness age 28-day look-back.
- `scripts/api_fields.py` can read Garmin's specification: `--spec`, `--write-spec`, `--check-spec`, `--diff-spec OLD NEW`,
  `--table`, `--write-readme`. New `tests/test_spec_fields.py` fails when the specification file changes or has fields that
  the integration neither reads nor lists in `docs/api-fields/spec-unused.json` (deliberately not used).

### Changed
- The fitness age answer is read as a list of records (as in Garmin's specification) as well as a single object; from a list
  the newest record that has a fitness age is used. The request itself is unchanged.
- A failed request now carries Garmin's own explanation for HTTP 400 (for example an unknown activity type) and for HTTP 404
  of an activity, shortened to 200 characters and without keys, tokens or headers; it appears in the service error.
- Timestamps that arrive as text holding epoch milliseconds (sleep start and end) are read.
- README: the statements on Body Battery (about 6 points) and SpO2 (hourly averages) now say which request they refer to and
  that the specification offers more (`chunks`, `spO2SingleValues`); both are untested and not used yet.

## 0.5.7

### Added
- Translations for newly seen Garmin keywords: sleep feedback and insights, personal sleep insights, HRV feedback (balanced, unbalanced, low with their number), sleep alignment, Body Battery level "moderate" and the rating "invalid".

## 0.5.6

### Fixed
- Initial history load: an empty answer from Garmin (HTTP 204, no body) no longer marks a day as finished and no longer
  sets the lower limit for good. Such days are asked again after a week; a limit found without real answers lapses after a
  week, and limits written by older versions are checked once again. Days Garmin answers with real, empty data stay finished.
- Initial history load: a day that keeps failing (three tries) is put off (1, 2, 4 ... at most 7 days) and the load goes on
  with the older days instead of stopping there at every sync. Two such days in a row end the run; the next run continues.
- Yesterday's evening is now fetched after the first sync that follows one from before midnight, also after 10 o'clock.
  The initial load starts at the day before yesterday and never finishes yesterday (the live filling takes care of it).
- Interrupting a write (reload, shutdown) now notes the points already handed to the recorder in the ledger and saves it, so
  nothing is written twice afterwards.
- The hourly-statistics and live-history job is bound to the config entry and is stopped (and awaited) when the entry is
  unloaded; no second job and no second ledger after a reload. The ledger is loaded once even if two parts ask at the same time.
- Switching off empty sensors once (first start after 24 hours with a sync of the day) is wired up for real: it uses the age
  of the entry, and it is only marked as done when the decision could be taken.
- The *last activity* sensors are never switched off by that cleanup any more (a strength workout without heart rate or
  distance used to switch off heart rate and distance for good).
- Groups (sleep, body, activities, profile) whose first refresh failed at the start are asked again after 5 minutes
  (up to three times) instead of staying unavailable until their regular interval.
- *Floors climbed* and *Floors descended* show Garmin's value unchanged (it was rounded to a whole number, so the total could
  fall back); weight, muscle mass and bone mass are no longer rounded to two places (display precision only).

### Changed
- All services (`fetch`, `search_activities`, `download_activity`, `backfill_statistics`, `backfill_intraday`,
  `backfill_history`) are now administrator-only. Automations and scripts are not affected.

## 0.5.5

### Fixed
- The history sensors now show the last value with its time (`measured_at`) even when the first live fill ran before the sensor was added (for example right after a restart). Before, they stayed *unknown*.

## 0.5.4

### Changed
- The history sensors (*Heart rate / Body Battery / SpO2 / HRV (history)*) are regular sensors of the device again, no longer in the
  *Diagnostic* category. They are still disabled by default.

## 0.5.3

### Added
- New history series **HRV (history)** (`hrv_history`, disabled by default, ms): the nightly HRV readings
  (about every 5 minutes) from the HRV endpoint, time from `readingTimeGMT` (UTC). A night belongs to the day of waking
  up; the ledger works with exact timestamps, so today's night is fetched again after each sync and only new points are
  appended. Available in `backfill_history` (`series: hrv`), the automatic live filling and the initial load, with the
  same per-series resume and re-load rules as heart rate. No hourly statistic for HRV.

### Changed
- Each history sensor now shows the value of its newest point as state, with `measured_at` (ISO, with zone) as
  attribute. Only the live filling sets it (point newer than the shown one; no new row otherwise); the initial load and
  old-day service runs never do. Restored after a restart; the progress attribute keeps the value.
- The SpO2 parser takes the `spo2Level` column from Garmin's descriptor list (column 1 as before if there is none);
  the environment column is never read.

## 0.5.2

### Added
- Option **Fill history automatically** (on by default). For each series whose history sensor is enabled and recorded
  (checked before every run; otherwise silently nothing, plus a repair hint if the recorder excludes an enabled
  sensor): after each sync the new points of today (and of yesterday on the first full refresh of a day and after
  syncs before 10:00) are appended, append-only through the ledger. A background load fills the past per series,
  backwards from yesterday up to the recorder's `keep_days` (10 if unknown, at most 400): one day at a time about 20 s
  apart, 30 minutes pause after a rate limit, stop after 14 empty days in a row, resumable (finished days are kept in
  the ledger per series, so enabling a series later or gaps after downtime are filled on the next reload), never
  parallel to the backfill services. Progress is shown as `history_backfilled_until` on the history sensor.

### Changed
- `backfill_history` is no longer experimental: `confirm_experimental` is gone, `series` is optional (default all
  three), up to 31 days per call.
- Hourly statistics are named like `Alex heart rate (hourly)`; the calendar uses a decimal comma for languages that
  have one and a readable title (`Trail running`) for unnamed activities; ages use the unit `y` instead of `a`.

## 0.5.1

### Added
- EXPERIMENTAL: `backfill_history` now writes. The real measuring points of one series are put into the recorder as
  states of the (history) sensor with their own timestamps, via the recorder's own queue (not supported by Home
  Assistant, only tested against fakes). Requires `confirm_experimental: true` (default false: the service answers
  `history_write_unsupported` and does nothing), exactly one `series` and at most 2 days per call. The sensor must
  exist, be enabled and be recorded; each point's `old_state` is the previous point; a failed hand-over stops at once
  and only the points really handed over enter the ledger. No automatic variant, no option.

## 0.5.0

### Added
- Hourly statistics for heart rate, Body Battery and SpO2: minimum, maximum and mean of the real Garmin measurements
  per full UTC hour, as external long-term statistics `garmin_personal:<entry_id>_heart_rate_hourly`,
  `…_body_battery_hourly` and `…_spo2_hourly` (bpm, %, %). Hours without measurements stay empty; placeholder values
  (0 or negative) are dropped; nothing is interpolated.
- New option **Write hourly statistics** (on by default, independent of the intraday attributes): after each new
  watch sync the completed hours of today are written, and those of yesterday on the first full refresh of a day and
  after syncs before 10:00 local time. Same statistic and hour overwrite each other, so later corrections by Garmin are
  taken over; the running hour is never written. Costs about 2 extra requests per sync (heart rate and Body Battery;
  SpO2 is reused) and 3 for yesterday (see README, request volume).
- New service `garmin_personal.backfill_intraday`: writes the hourly statistics retroactively (`days`, `start_date`,
  `end_date`, `config_entry_id`; at most 366 days, one request per day and series, one run per account at a time,
  partial result with `complete`, `last_completed_day` and `error` after an interruption).

- Scaffold for history sensors: disabled diagnostic sensors *Heart rate / Body Battery / SpO2 (history)* and the
  service `backfill_history` with an append-only ledger (`history.py`: exact timestamps for 7 days, marks for older
  days, recorder check when the ledger is lost, `confirm_rewrite`). The service answers `history_write_unsupported`
  until writing states with past timestamps is verified on a real Home Assistant; nothing is written or requested.

### Changed
- The metadata of external statistics is now built in one place (`stats_writer.py`); the existing daily statistics are
  unchanged.

## 0.4.0

Requires Home Assistant 2025.10.0 or newer (`hacs.json`).

### Added
- Help texts for the setup, reauthentication, reconfigure and options dialogs; links to the Garmin key page; the
  key validity is described as an estimate and is preset with your last choice.
- Translated service errors (English and German) with the accounts listed when several exist; endpoint names in the
  `fetch` dropdown; examples in the service forms.
- `backfill_statistics` reports `complete`, `last_completed_day`, `error`, `days_imported`, `statistic_series` and
  `statistic_rows`; imports run in 31-day windows, one per account at a time.
- Repair issue `key_expired` (error) after the calculated expiry date; the issue is checked hourly.
- Richer diagnostics (key expiry source, update groups, endpoints with and without data, disabled entities), still
  without key, account ID, name or measurements.
- Entry removal also deletes the repair issue and the internal activity marker; imported statistics stay.
- CI: tests, `ruff` and hassfest run before a release; `quality_scale.yaml`; Dependabot for actions.
- README (English and German) rewritten: what you see after setup, two people, examples, service example with several
  accounts, statistics card for imported values, troubleshooting, removal.
- `scripts/gen_translations.py --check` and `tests/test_i18n_*.py` keep names, word lists, texts and icons consistent.

### Changed
- The account is identified by Garmin's profile ID instead of the display name; existing entries are switched over
  automatically at the first start, entities and history stay. A name is now required when adding an account, and a
  missing account ID aborts the setup with an error.
- The options dialog reloads the entry by itself (no update listener).
- `backfill_statistics` ends yesterday by default (today only with an explicit `end_date`), accepts at most 3650 days,
  skips a day value of 0 for resting/minimum/maximum heart rate, stress and respiration, and takes one entry per day.
  The result field `statistics` is replaced by `statistic_series` and `statistic_rows`.
- `download_activity` writes to `<media folder>/garmin_personal/activity_<id>.zip` by default, accepts only `.zip`
  targets and writes atomically.
- Without `config_entry_id` the services use the only account; with several accounts the field is required.
- Activity filters such as `favorite` are validated as booleans.
- The calendar ends an activity at the elapsed duration when Garmin delivers it, shows distances in your unit system and
  its current event is only a running or the next upcoming activity.
- The event entity reports activities found before it existed (restart) and every activity of an update cycle. Its
  type is now shown as "New activity" / "Neue Aktivität"; the technical key `activity_finished` is unchanged.
- The key expiry sensor works locally and no longer depends on the profile request.
- Start coordinates, place name, description and other large attributes of the sensors are excluded from the
  recorder; the description is limited to 255 characters.
- The four stress duration sensors use the state class `total_increasing` (Home Assistant may show a one-time
  statistics repair for them; they are disabled by default).
- German sensor names reworded (grammar, one pattern for average/lowest/latest values, "Atemfrequenz", "Atemstörungen"
  instead of "Atemaussetzer"); clearer English names for rest stress and heart-rate sensors; value texts translated
  strictly literally.
- The stress level has no `unknown` value any more: Garmin's `UNKNOWN` is shown as Home Assistant's empty state.
  The sensor "Breathing disruption" has no word list; each value seen is added and logged once.
- Icons come from `icons.json`, generated from a table in the generator.
- One-time disabling of empty sensors only affects body and activity sensors, only for entries at least 24 hours old
  that have synced on the same day; the keys are logged.

### Fixed
- Weight and BMI no longer show profile changes or zero values as weighings; negative placeholders and zero values for
  "not measured" are treated as no value; HRV uses the newest day with a night average; Body Battery events read the
  right column; rounding is consistent.
- Sleep sensors treat a night of 0 seconds as not measured and keep the last value.
- Day change: daily values never carry into the next day; the first sync after a restart triggers the follow-up groups.
- Short outages, rate limits (`Retry-After` is honoured, one shared pause) and malformed responses no longer turn
  all sensors unavailable at once; a 403 HTML page from Garmin no longer starts re-authentication.
- Parallel 401 answers cause one token exchange; the token exchange backs off and has a cool-down.
- The sync-overdue sensor keeps working after midnight; `fetch` uses Home Assistant's local date.
- Activity events are no longer flooded after an empty or failed first answer.

## 0.3.8
- New calendar entity with the latest activities (start, duration; distance, calories and average heart rate in the description).
- New sensors (disabled by default): stress shares (total, rest, activity, low, medium, high), average altitude,
  highest/lowest respiration, lowest/highest average heart rate, Body Battery level (with Garmin's feedback and events
  as attributes), sleep alignment (Garmin's recommended window, as delivered).
- Icons moved to `icons.json`.

## 0.3.7
- Sleep, HRV and body sensors keep their last known value while Garmin returns nothing, also across restarts.
  Attributes `held_value` and `last_seen` show when a value is old. Nothing is estimated.

## 0.3.6
- HRV feedback is shown as "Balanced: N" / "Ausgeglichen: N" (number only, no interpretation, because the API
  provides no scale).

## 0.3.5
- New sensor: personal sleep insight (19 observed variants, English and German).
- HACS downloads via the API zipball again, because the release-asset redirect from github.com carries a header
  that is too large for Home Assistant's HTTP client.

## 0.3.4
- All observed sleep feedback and sleep insight values are translated; unknown values are logged once at info level
  and never hidden.

## 0.3.3
- Sleep feedback and sleep insight (observed keys) in English and German.

## 0.3.2
- `backfill_statistics` also writes sleep, HRV and weight/body values into the long-term statistics.
- README: translations, history and long-term statistics.

## 0.3.1
- Fixed word lists from Garmin (rating, HRV status, stress level, activity type) are translated (English, German).

## 0.3.0
- Release workflow publishes a ZIP asset; tag and release are created automatically when the manifest version changes.
- Backfill: optional steps, distance and floors from other apps (e.g. RunGap) via `include_third_party_steps`.

## 0.2.x
- Source filter (GARMIN only), placeholder days skipped, sync detection after midnight, sleep value qualifier,
  sync warning threshold 18 h.
- Fix: first activity after an empty history is reported; download write errors raised as Home Assistant errors.
- Tests for config flow, services, setup, entities and coordinators.
- Sync time checked every 5 minutes, the other endpoints fetched only after a new sync.

## 0.1.0
- First version: all 26 read endpoints of the Garmin Connect Personal API as sensors and services.
