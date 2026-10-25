# Backlog

Ideas and open points, roughly by priority. Nothing here is promised; items move to the changelog when released.

## Planned
- **Hourly statistics from intraday series** (heart rate, Body Battery, SpO2): min/max/mean per full hour from the real
  Garmin points, written continuously and via `backfill_intraday` (in development, 0.5.0).

## Needs a live test (read-only, with `garmin_personal.fetch` since 0.5.8)
- Body Battery `chunks` (12, 48, 96, 288): does the series get denser? Then use it for the sensors and bump the history ledger.
- `spO2SingleValues` of the SpO2 answer: filled? Then read the raw series instead of the hourly averages.
- Fitness age: real shape (list or object) and `full_history_scan: true`.
- `weights_all`: still HTTP 400? Weight range with `include_all: false`.
- Daily summaries (V2) against the live sensors: minimum/maximum heart rate, distance and respiration differ in meaning
  (see README, "backfill_statistics"); compare one real day before changing any existing statistic.

## To think about
- **Raw intraday points in full resolution.** Home Assistant statistics only accept full hours and the recorder drops
  large attributes, so the real points (heart rate about every 2 minutes; Body Battery, SpO2 and stress to be checked
  against real responses) have no good home inside HA yet. Options to evaluate:
  - time-series database (InfluxDB) fed by the integration, nightly for the previous day plus a one-time backfill;
  - one file per day and person (JSON/Parquet) in a configurable folder;
  - **recorder states with historic timestamps** (wanted, to be tested): real points written as ordinary states into the
    recorder, so the History panel shows them like live values. Home Assistant has no supported service for this and
    purges states after `purge_keep_days`, so it needs (1) a dedicated history entity per series, not the live sensor,
    (2) a much longer `purge_keep_days` (PostgreSQL recommended, roughly 1.5 million rows per year for Garmin points
    of two people), (3) a small test first: one series, one day, check History panel, purge behaviour and database
    growth, before importing a year. May break with future Home Assistant versions.
  No interpolation or resampling: only the points Garmin delivers.
- Option to merge backfilled statistics into the live sensors' own statistics (only for point-in-time values such as
  resting heart rate, sleep score, HRV, weight).
- Hydration goal sensor, BMI fallback, weight source option.
- Goals and badges (check what the Personal API delivers), route polyline (unverified).
- Repair hint after several days without data.
- Separate client library on PyPI; `pytest-homeassistant-custom-component` tests next to the stub tests.
- Weekly check for new Garmin fields (`scripts/api_fields.py`) with baselines for the remaining endpoints.

## Known small points
- Unit of the fitness age sensor ("a"), calendar description decimals and fallback title, English display names of
  the backfilled statistics.
