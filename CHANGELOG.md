# Changelog

All notable changes to the Garmin Connect Personal API integration. Versions follow `manifest.json`;
each GitHub release shows the matching section.

## Unreleased

### Added
- New history series **HRV (history)** (`hrv_history`, diagnostic, disabled by default, ms): the nightly HRV readings
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
