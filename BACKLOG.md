# Backlog

Ideas and open points, roughly by priority. Nothing here is promised; items move to the changelog when released.

## Planned
- **Hourly statistics from intraday series** (heart rate, Body Battery, SpO2): min/max/mean per full hour from the real
  Garmin points, written continuously and via `backfill_intraday` (in development, 0.5.0).

## To think about
- **Raw intraday points in full resolution.** Home Assistant statistics only accept full hours and the recorder drops
  large attributes, so the real points (heart rate about every 2 minutes; Body Battery, SpO2 and stress to be checked
  against real responses) have no good home inside HA yet. Options to evaluate:
  - time-series database (InfluxDB) fed by the integration, nightly for the previous day plus a one-time backfill;
  - one file per day and person (JSON/Parquet) in a configurable folder;
  - recorder states with historic timestamps: not supported by Home Assistant, would need direct database writes
    and is purged after `purge_keep_days`; rejected for now.
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
