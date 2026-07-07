# Changelog

## [Unreleased]

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

## [0.2.2] - 2026-07-05

### Added
- **Temperature in per-activity time-series samples** (`activity_samples` table / the
  `activity_samples` MCP tool): Garmin's per-second chart data includes ambient temperature for
  devices that record it (`directTemperature`), alongside the existing pace/HR/cadence/elevation
  fields — previously fetched but discarded. New `temperature_celsius` column, nullable like
  every other sample field for devices/activities that don't report it. Existing databases get
  the new column via an explicit migration on next startup (`CREATE TABLE IF NOT EXISTS` alone
  doesn't add columns to an already-existing table).

### Changed
- **Rewrote `DOCS.md`'s Claude connection instructions** (milestone v0.9) into two concrete
  setups: Claude Desktop (direct LAN, via `mcp-proxy`) and Claude mobile (via an existing
  Cloudflare Tunnel install). Also documents a real limitation discovered while writing this:
  Claude's "Add custom connector" UI has no field for a static bearer token (OAuth or no-auth
  only), and the MCP server 401's every request when `mcp_auth_token` is set — including
  Claude's own connector, since it can never send one. So `mcp_auth_token` must be left empty for
  the mobile/connector setup to work at all; real protection there comes from a Cloudflare WAF
  rule restricting the tunnel hostname to Anthropic's published MCP-connector egress IP ranges
  instead. Added an "Example prompts" section covering run analysis and racing/target-pace
  questions by training type.

### Fixed
- **"Log in again" silently did nothing for MFA-enabled accounts with an existing session**:
  `Garmin.login()` always prefers resuming a still-valid cached session over a real
  credentials-based login, entirely skipping the MFA challenge, even when the user explicitly
  clicked "Log in again" wanting a genuine re-authentication — reported live by an MFA-enabled
  account that never saw the MFA prompt. `mfa_login.start_login()` gained a `force` parameter
  (passes `tokenstore=None` instead of the real token directory, so `Garmin.login()` has nothing
  to resume from) used whenever a cached session already exists; a failed forced re-login never
  touches the existing session on disk, so scheduled syncs keep working with the old session if
  the new attempt fails.

[0.2.2]: https://github.com/nsaputro/stride-sync/releases/tag/v0.2.2
