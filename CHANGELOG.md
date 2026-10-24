# Changelog

All notable changes to the Garmin Connect Personal API integration. Versions follow `manifest.json`;
each GitHub release shows the matching section.

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
