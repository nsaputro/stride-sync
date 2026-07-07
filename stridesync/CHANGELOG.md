# Changelog

## [Unreleased]

### Changed
- **Diagnostics panel: `resting_hr`/`vo2max` renamed to `resting_hr_latest`/`vo2max_latest`,
  searching backward from today for the most recent available date instead of hardcoding
  "today"**: both fields can legitimately be missing for today specifically because Garmin
  hasn't finalized them yet, which previously looked identical to a wrong field-name guess in
  the diagnostic output. The response now includes which date the data actually came from.

### Fixed
- **`vo2max_history` silently syncing rows with every field `NULL`, despite the account having
  real VO2 max history in the Garmin Connect app** (milestone Stage 12 follow-up): the "list
  means unexpected shape, degrade to no data" guard added in `0.3.1` was itself the bug —
  `get_max_metrics`'s real successful response is a list containing one dict
  (`[{"generic": {...}, ...}]`), not a bare dict, so that guard was silently discarding every
  real response instead of only the genuinely-empty ones. `_normalize_vo2max` now unwraps that
  list before extracting fields, confirmed against a real account's Diagnostics panel output
  (`vo2MaxPreciseValue: 55.2`). Also fixed `fitnessAge`, which actually lives nested under
  `generic`, not at the top level as originally guessed.

## [0.3.1] - 2026-07-07

### Added
- **Diagnostics panel: wellness/VO2 max checks** (milestone Stage 16 follow-up): six new checks
  (`sleep_data`, `hrv_data`, `training_status`, `training_readiness`, `resting_hr`, `vo2max`) in
  the Settings tab's Diagnostics dropdown, added after a live report that an account with real
  VO2 max and HRV history in the Garmin Connect app was getting `NULL` for both in StrideSync —
  the same wrong-field-name-guess failure class as `planned_workouts`, not yet pinned to a
  specific key. Exposes the raw response for each of `fetch_daily_wellness`'s five sub-calls
  plus `fetch_vo2max`'s one, the same way the training-plan checks did for that earlier fix.
- **Dashboard shows per-record-type sync totals, not just activities** (milestone Stage 13
  follow-up, requested live): the Dashboard tab now also shows total `daily_wellness`,
  `vo2max_history`, and `planned_workouts` row counts alongside the existing
  "Total activities synced" stat — previously that breakdown was only visible in the add-on log
  lines, not the web UI.

### Fixed
- **VO2 max backfill log noise**: `fetch_vo2max`'s "unexpected response shape" line fires once
  per calendar date whenever Garmin has no VO2 max estimate for that date — confirmed live as
  the routine case for older dates, not a rare anomaly — so a months-long backfill was logging
  one `WARNING` per missing date. Downgraded to `DEBUG`; the non-fatal "treat as unavailable"
  behavior itself is unchanged.

[0.3.1]: https://github.com/nsaputro/stride-sync/releases/tag/v0.3.1
