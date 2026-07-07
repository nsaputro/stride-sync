# Changelog

## [Unreleased]

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

## [0.3.0] - 2026-07-07

### Added
- **Daily wellness sync** (milestone v0.12): new `daily_wellness` table — sleep (score, duration,
  deep/light/REM/awake seconds), HRV (status, weekly/last-night averages), Garmin's own
  training-status label and training-readiness score, and resting HR. One row per calendar date,
  refetched for a rolling 4-day window (today + previous 3 days) on every sync to catch Garmin
  finalizing sleep/HRV data a day late. The five underlying endpoints are wrapped individually
  rather than as one group, since HRV/sleep/readiness support varies independently across
  devices — one endpoint failing no longer discards data that successfully came back from the
  other four. New MCP tools: `daily_wellness(days=14)`, `resting_hr_trend(days=30)`.
- **VO2 max trend** (milestone v0.12, `vo2max_history` table, `get_max_metrics`): running/cycling
  VO2 max and fitness age, same rolling-window daily fetch as the wellness metrics — additive to
  the existing `training_baseline` table/tool, not a replacement. New MCP tool:
  `vo2max_trend(days=90)`.
- **Training plans: planned vs. actual** (milestone v0.12, `planned_workouts` table,
  `get_training_plans`/`get_training_plan_by_id`): scheduled workouts from an active Garmin
  Connect training plan, if one is configured — refetched for a rolling ±14-day window on every
  sync. Accounts with no active plan degrade to an empty table, not a sync failure. New MCP tool:
  `planned_vs_actual(days=14)`, joining planned workouts against completed activities by calendar
  date. This is the most speculative addition in v0.12 — the underlying `get_training_plans`/
  `get_training_plan_by_id` response shape has no prior confirmation from a live account.
- **Diagnostics panel on the Settings tab** (milestone v0.16): runs a read-only raw Garmin
  Connect API call and shows its exact JSON response, so a synced field that's coming back wrong
  or missing can be diagnosed and reported without needing shell/docker access to the add-on.
  Backed by a fixed, curated set of checks (`GarminClient.fetch_diagnostic`) — never an arbitrary
  method name, since several `python-garminconnect` methods are write operations and StrideSync
  never writes back to Garmin. Includes a copy-to-clipboard button on the output, so the raw JSON
  doesn't need to be manually selected out of the (often long) scrollable box.

### Changed
- **Scheduled sync now fetches activities incrementally instead of a fixed most-recent-20**
  (milestone v0.13): `run_sync_once` fetches everything since the last *successful* sync's date
  (falling back to a 7-day lookback on an account's very first sync ever) instead of always the
  most recent 20 — a fixed count could silently miss older activities logged during a busy
  stretch. A failed sync doesn't count as "last successful," so a retry re-covers the same range
  rather than skipping past whatever the failed attempt never actually synced. The now-unused
  `--limit` CLI flag was removed along with it.
- **Sync log now reports a per-record-type count**, not just activities (milestone v0.13):
  `daily_wellness`, `vo2max_history` (only counting dates Garmin actually returned data for), and
  `planned_workouts` row counts are logged on every sync pass, success or failure — confirming
  what actually synced no longer requires a direct database query.
- **Backfill now has parity with regular sync** (milestone v0.14): `run_backfill_sync` refreshes
  `training_baseline`, and fetches `daily_wellness`/`vo2max_history` for every date from the
  given start date through today (not just a fixed rolling window), so historical wellness/VO2
  max data is actually backfilled, not just activities. `planned_workouts` is refreshed too,
  using the same forward-looking window as regular sync (it's not historical data). Backfill now
  also logs per-record-type counts, matching v0.13's regular-sync change.

### Fixed
- **Sync crash when `get_max_metrics` returns a list instead of a dict** (milestone v0.12):
  confirmed live on a real account — `GarminClient.fetch_vo2max`'s normalization step ran
  *outside* its try/except, so the resulting `AttributeError` propagated all the way through
  `run_sync_once` (which only catches `GarminAuthError`/`GarminAPIError`), crashing the entire
  sync pass without even recording a `sync_log` failure row. Fixed by moving the normalize call
  inside the try/except and hardening it against non-dict input; applied the same defensive fix
  to `fetch_daily_wellness`'s merge step, since it has the identical unguarded-call shape and the
  same live account demonstrated Garmin's API can return unexpected response shapes.
- **Backfill button looping forever, restarting the backfill every ~1 second** (milestone v0.14):
  confirmed live — the Settings tab's backfill POST handler rendered the progress page directly
  instead of redirecting, so the polling script's `location.reload()` (fired once it saw the
  backfill finish) re-submitted the original POST rather than doing a plain GET, silently
  restarting the backfill forever until the container was restarted. Fixed with the standard
  Post/Redirect/Get pattern: the POST handler now redirects to the `GET /backfill` route instead
  of rendering the page itself.
- **`planned_workouts` silently syncing zero rows for accounts with a real active training
  plan** (milestone v0.15): confirmed live — a real training plan (screenshotted from the Garmin
  Connect app) produced "0 planned workouts" on every sync. Root cause: `get_training_plans()`'s
  actual top-level key is `trainingPlanList`, not the `trainingPlans`/`plans` originally guessed
  — confirmed directly from `python-garminconnect`'s own bundled `demo.py`, not another guess —
  so the plan list was never found. Also resolved the previously-open question of which plan type
  needs `get_adaptive_training_plan_by_id`: a plan's `trainingPlanCategory` field equal to
  `"FBT_ADAPTIVE"` routes there; everything else uses the phased `get_training_plan_by_id`. The
  training-plan detail response's own shape is still unconfirmed — a follow-up fix is pending
  live-account output.
- **`planned_workouts` still syncing zero rows after the `trainingPlanList` fix** (milestone
  v0.17): the reporting user's real training plan (pasted via the new Diagnostics panel) revealed
  the actual remaining cause — a plan entry's own id field is `trainingPlanId` (an integer), not
  `planId`/`id` as originally guessed, so `plan_id` extraction always failed and every plan was
  silently skipped. Also confirmed live that the `FBT_ADAPTIVE`-routing fix from v0.15 is correct
  for this account. Also raised the Diagnostics panel's output cap from 8000 to 60000 characters
  — a real `scheduled_workouts` check response was truncated before reaching the dates that
  mattered.
- **`planned_workouts` workout names/types/durations confirmed and fixed end-to-end** (milestone
  v0.18): with `plan_id` extraction fixed, the reporting user's next sync reached the real
  `get_adaptive_training_plan_by_id` response and pasted it back complete. The scheduled-day list
  key is `taskList`, not `workouts`/`scheduledWorkouts`/`days`; workout name/type/duration live
  nested under `taskWorkout.{workoutName, trainingEffectLabel, estimatedDurationInSecs}`, not on
  the day entry itself — verified byte-for-byte against that account's own Garmin Connect app
  (`3660`/`3120`/`5100`/`3000` seconds matched `"1:01:00"`/`"52:00"`/`"1:25:00"`/`"50:00"` for
  the same workouts). Rest days (`taskWorkout.restDay: true`) are now correctly excluded rather
  than stored as empty placeholder rows. No structured pace/HR target field exists in the real
  response (Garmin uses free text like `"2x18:00@162bpm"` instead), so
  `planned_target_pace_sec_per_km`/`planned_target_hr_low`/`planned_target_hr_high` remain `None`
  for now.

[0.3.0]: https://github.com/nsaputro/stride-sync/releases/tag/v0.3.0
