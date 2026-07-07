# Changelog

All notable changes to StrideSync are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions match `stridesync/config.yaml` and the GitHub release tags.

---

## [Unreleased]

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

## [0.2.1] - 2026-07-05

### Added
- **New "Settings" tab with a one-off activity backfill** (milestone v0.8): regular syncs are
  count-based (the most recent N activities), so there was no way to pull in older history
  beyond whatever that covers. Pick a start date and StrideSync fetches every activity from then
  through today via Garmin's date-range endpoint (`GarminClient.fetch_activities_since`), reusing
  the same per-activity write path a regular sync uses (`scheduler.run_backfill_sync`, sharing
  `_sync_activities` with `run_sync_once` rather than duplicating it). Doesn't touch
  `training_baseline` — that stays the regular scheduled sync's job.
- **Live progress bar for the backfill**: a wide date range can take a while (several Garmin API
  calls per activity), so the backfill now runs in a background thread instead of blocking the
  request. The Settings tab polls `GET /backfill/status` and shows a `<progress>` bar with a
  live "N / total activities" count; you can navigate away and back without losing progress, and
  a second backfill can't be started while one is already running.

### Fixed
- **"database is locked" errors on the web UI during a backfill**: the sync scheduler and
  backfill hold a single write connection open across many commits, and any page load hitting
  the DB at the wrong moment (e.g. the **Running** tab) could raise
  `sqlite3.OperationalError: database is locked` instead of just waiting, since the DB used
  SQLite's default rollback-journal mode with no busy timeout. Switched `/data/stridesync.db` to
  WAL mode (readers never block on the one writer) and added a 5s busy timeout to every
  connection as defense-in-depth.
- **Backfill progress bar disappearing when switching tabs**: the "Settings" nav tab always
  rendered the plain start-a-backfill form, regardless of whether a backfill was already running
  — so switching to another tab mid-backfill and clicking back into Settings made the progress
  bar (and the running backfill itself) look like it had vanished. Settings now shows the live
  progress bar while a backfill is running, and the last backfill's result/error once it's done.

## [0.2.0] - 2026-07-05

### Added
- Pre-release/dev channel: `stridesync-dev/config.yaml` + `build.yaml` (slug `stridesync_dev`,
  host port `8766` alongside a stable install on `8765`) and
  `.github/workflows/prerelease.yml` (`workflow_dispatch`), so a fix can be built, pushed to
  GHCR under a pre-release tag, and installed/verified on a real HA instance before it's
  promoted to a stable release — added in response to v0.1.0 shipping with a startup bug (see
  below) that a build-only CI smoke test didn't catch.
- CI now actually **runs** the built Docker image and checks both s6 services start without
  crashing (previously it only built the image, which is exactly why the bug below shipped
  undetected through 6 PRs).
- **Ingress web UI for the one-time Garmin MFA login** (`app/mfa_web/server.py`, a new
  `mfa-web` s6 service on `ingress_port: 8767`): open the StrideSync panel in the HA sidebar and
  click "Log in to Garmin Connect" — an alternative to `python3 -m app.sync.bootstrap_login` for
  users without terminal/`docker exec` access, which not every HA user has set up. Shares the
  login/resume logic with the CLI bootstrap via a new `app/sync/mfa_login.py` module, so both
  entry points implement the flow exactly once. This revisits milestone v0.4's original "no
  ingress" decision — the MCP server itself still has no ingress route, since MCP clients reach
  it directly over the network, not through HA's UI.
- **"Sync now" button on the MFA login web UI** (shown once a session exists): triggers
  `scheduler.run_sync_once` on demand, reusing the exact same sync logic the sync-scheduler
  service runs on its interval, so a fresh login can be verified end-to-end without waiting for
  the next scheduled sync.
- **MFA login web UI now shows total activities synced and last-sync outcome** (status, time,
  activity count, error if any) directly on the panel, reading the same `sync_log`/`activities`
  tables the MCP server's `last_sync_status` tool already exposes — so staleness or a failed sync
  is visible without needing an MCP client.
- **Redesigned the MFA login web UI**: card layout, light/dark theme support (follows the
  browser's `prefers-color-scheme`), a clear primary action (Sync now once logged in, Log in
  otherwise), human-readable timestamps instead of raw ISO-8601 with microseconds, a numeric
  keypad + one-time-code autofill hint on the MFA input, and instant "Working…" button feedback
  on submit (logins/syncs are blocking network calls that can take several seconds).
- **Training-zone data for marathon pace/HR targeting** (milestone v0.5): average pace/HR per
  activity can tell you a run was fast or slow, but not whether it was the *right effort* for a
  marathon-training plan — that needs a physiological reference point and, ideally, effort
  distribution within a run. Three additions, all requested directly after reviewing synced data
  for exactly this use case:
  - `training_baseline` table: lactate threshold HR/pace and Garmin's own 5k/10k/half/marathon
    race predictions, fetched once per sync — the reference point that turns "average HR 150"
    into an actual effort level for a given athlete.
  - `activity_hr_zones` table: seconds spent in each HR zone per activity, not just its single
    average HR.
  - `activity_samples` table: fine-grained pace/HR/cadence/elevation time-series per activity
    (up to Garmin's ~2000-point cap), for cardiac-drift and precise negative-split detection at a
    finer resolution than 1km auto-lap splits.
  - Three new MCP tools (`training_baseline`, `activity_hr_zones`, `activity_samples`) expose all
    of this to Claude directly, rather than baking training-science formulas into this codebase.
  - Not every Garmin device/account has lactate-threshold/race-prediction data — that's handled
    as "nothing to store," never as a sync failure.
- **MFA login web UI's front page is now more of a dashboard**: below the total-activities/last-
  sync summary, it lists the most recent activities with their name, local start time, and
  distance (in km).
- **Optional bearer-token auth for the MCP server** (milestone v0.6), so it can be safely exposed
  beyond your LAN — e.g. through a Cloudflare Tunnel, to reach it from Claude on mobile. The MCP
  server had no auth by default (fine for LAN-only access, not fine once a public hostname points
  at it — it serves personal Garmin activity/HR/health data). New `mcp_auth_token` add-on option
  (empty = disabled, matching current behavior — nothing breaks for existing installs); when set,
  every request must include `Authorization: Bearer <token>` or gets rejected with `401`. See
  DOCS.md's "Remote access" section for the full Cloudflare Tunnel setup.
- **New "Running" tab on the MFA login web UI**, alongside the existing dashboard: shows total
  distance per calendar week (Monday–Sunday), most recent week first.

### Fixed
- **Add-on fails to start** (`ModuleNotFoundError: No module named 'app'`, both services): the
  Dockerfile's `COPY app/ .` flattened `app/`'s contents directly into `WORKDIR /app`, so
  `python3 -m app.mcp.server` / `app.sync.scheduler` couldn't find a package called `app` (every
  module in this codebase imports itself as `app.xxx`). Changed to `COPY app/ ./app/` to
  preserve the package directory. Affects every install of `v0.1.0`.
- **`rootfs/etc/cont-init.d/00-validate-config.sh` always reported credentials missing when run
  standalone** (no real HA Supervisor), killing the container even with valid `options.json` —
  found by the new CI container smoke test on the PR that fixed the bug above.
  `bashio::config.has_value` calls out to the Supervisor API (`curl: Could not resolve host:
  supervisor` outside a real HA install), so it always returned false standalone. Switched to
  plain `bashio::config` (reads `/data/options.json` directly, works both standalone and under a
  real Supervisor) + a shell emptiness check.
- **Both services crashed with `ValueError: invalid literal for int() with base 10: 'null'`
  (and, for `log_level`, `ValueError: Unknown level: 'NULL'`)** when run standalone:
  `bashio::config` for any schema-validated option type — int ranges, `port`, `list(...)`
  enums, not just numeric fields — emits the literal string `"null"` outside a real Supervisor,
  rather than the configured value. `app/config.py`'s `Settings.from_env()` now treats `"null"`
  (and an empty string) as "unset" for every field and falls back to the documented default,
  instead of crashing.
- **Login failed with a confusing generic error (`Garmin Connect login did not return valid
  tokens`) for accounts with MFA/2FA enabled**, and syncing didn't actually work for them at
  all: `garmy` doesn't raise an exception when MFA is required and no interactive prompt
  callback is supplied (StrideSync never supplies one — it runs headless) — it silently returns
  a `("needs_mfa", state)` tuple instead. Fixed properly, not just reported more clearly:
  `GarminClient.login()` now prefers a cached session (`AuthClient.is_authenticated`) or a
  refreshed one (`needs_refresh` → `refresh_tokens()`, which doesn't need MFA) over a fresh SSO
  login, which would otherwise re-trigger MFA on every single sync. A new one-time interactive
  CLI, `python3 -m app.sync.bootstrap_login`, performs the first MFA login and persists the
  session to `garmin_token_dir` (`/data/.garmin_tokens`) for every scheduled sync to reuse.
- **The MFA login web UI's "Log in to Garmin Connect" button returned a bare "Internal Server
  Error"** instead of a diagnosable message: `app/mfa_web/server.py`'s `start()`/`verify()`
  routes only caught `garmy`'s `AuthError`, not the transport-level failures (connection errors,
  timeouts, an unexpected non-JSON response from Garmin) that `garmin_client.py` already knows
  to expect and wrap — most likely to surface here because `sync-scheduler` also attempts a
  login at container startup, independently of the web UI. Now catches
  `requests.exceptions.RequestException` (matching `garmin_client.py`'s `_TRANSPORT_ERRORS`) plus
  a catch-all for any other unexpected exception, always rendering a clear error page instead of
  crashing.
- **`sync-scheduler` retried a fresh Garmin SSO login every `sync_interval_hours` even after
  learning the account needs MFA** — an unbounded automated-login retry against Garmin's
  unofficial API that PROJECT_PLAN.md's "no auto-retry storms" design guidance specifically
  warns risks the account being flagged, and one that could never succeed anyway without the
  one-time bootstrap. `GarminClient.login()` now persists a `.mfa_required` marker next to the
  token files after the first such attempt and fails fast (no network call) on every subsequent
  call while the marker is set, clearing it automatically once `bootstrap_login.py` or the web UI
  completes the one-time login.
- **Garmin login started failing with `401 Client Error: Unauthorized` on the plain SSO signin
  page**, before credentials were even submitted — confirmed via live testing that the identical
  URL worked instantly from a real browser on the same account, isolating the cause to the
  request itself rather than the URL or account. Root cause: `garmy`'s Android User-Agent is the
  literal Android package name (`com.garmin.android.apps.connectmobile`), not a real User-Agent
  string, and identical across every install — an easy target for Garmin/Cloudflare's bot
  detection. A new `app/sync/garmy_ua_override.py`, applied once by every entry point that talks
  to Garmin, replaces it with a properly-formatted mobile-app-style value
  (`GARMIN_ANDROID_USER_AGENT` env var to override further). Not guaranteed to be the complete
  fix — Cloudflare-class bot detection can also fingerprint at the TLS/connection level — but a
  concrete, low-risk thing to try first.
- **The User-Agent fix above didn't fully resolve a real account's 401** — confirmed by live
  retesting on a rebuilt image. Since the bare exception message alone can't tell a
  Cloudflare-level block from a plain Garmin-side rejection, `garmin_client.py`'s error messages
  now include diagnostic detail when a response is available (`server`/`cf-ray` headers, a short
  body snippet), reused by the web UI, `bootstrap_login.py`, and the scheduler — to get real
  signal on the next failure instead of guessing further.
- **`bootstrap_login.py` (the CLI MFA login) crashed with an unhandled traceback on any
  network/HTTP error** (e.g. the same Garmin SSO 401 above) — unlike the web UI and scheduled
  sync, it only caught `garmy`'s `AuthError`, not transport-level failures. Now handles them the
  same way as the other two entry points.
- **Root cause of the SSO 401, finally confirmed**: the new diagnostic detail above showed
  `server=cloudflare` and a `cf-ray` header with an HTML challenge-page body — this is Garmin's
  Cloudflare bot management blocking the request at the TLS/connection level, the same
  ecosystem-wide event that deprecated `garth` entirely in March 2026 and forced
  `python-garminconnect` to adopt TLS-fingerprint impersonation (`curl_cffi`) to keep working. No
  header change (like the User-Agent fix above) can defeat this. New
  `app/sync/garmy_tls_impersonation.py` applies the same `curl_cffi` fix to `garmy`'s SSO login
  flow specifically (a new dependency, `GARMIN_TLS_IMPERSONATE` env var to override the
  impersonated browser).
- **TLS impersonation alone still didn't clear the Cloudflare challenge** — confirmed by live
  retesting (the error message format changed, proving `curl_cffi` was genuinely used, but the
  same challenge came back). `python-garminconnect`'s actual current implementation does the same
  TLS impersonation *and* adds a randomized 3-8 second delay between fetching the login page and
  submitting credentials, treating request timing as a separate Cloudflare signal from the TLS
  handshake. New `app/sync/garmy_login_delay.py` reproduces this (`GARMIN_LOGIN_DELAY_MIN_S`/
  `GARMIN_LOGIN_DELAY_MAX_S` env vars to override).
- **None of the three fixes above (User-Agent, TLS impersonation, login delay) cleared Garmin's
  Cloudflare challenge** — confirmed by live retesting after each one. Rather than layer a fourth
  `garmy`-specific patch, **migrated the Garmin Connect library from `garmy` to
  `python-garminconnect`**, which already implements a 5-strategy cascading login chain (mobile
  app API / web widget / full portal, each tried with both `curl_cffi` TLS impersonation and
  plain `requests`, falling through to the next strategy on any non-credential/non-MFA failure)
  plus its own anti-bot timing delays, and is actively maintained against Garmin's changes.
  Removed `garmy_ua_override.py`, `garmy_tls_impersonation.py`, and `garmy_login_delay.py` (and
  their tests); rewrote `garmin_client.py`, `mfa_login.py`, `bootstrap_login.py`, and
  `mfa_web/server.py` against the new library's `Garmin`/`Client` API, carrying over the same
  cached-session-first login ordering and `.mfa_required` no-retry-storm marker behavior.
- **The MFA login web UI failed with `Login failed: Username and password are required`** on the
  very first login attempt (the whole point of the UI — no cached session yet): unlike
  `sync-scheduler/run`, the `mfa-web` s6 service's `run` script never exported
  `GARMIN_USERNAME`/`GARMIN_PASSWORD`, so the web UI always saw empty credentials regardless of
  the add-on's configuration. Pure-Python tests never caught this since they call `create_app()`
  directly, bypassing the run script entirely. Fixed the run script, and added an explicit
  missing-credentials check to `mfa_web/server.py`'s `start()` (matching `bootstrap_login.py`'s
  existing one) so a genuinely misconfigured install fails with a clear message instead of the
  library's generic one.
- **Confirmed on a real HA install: the `python-garminconnect` migration works.** Login through
  the ingress web UI completed successfully — `python-garminconnect` gets past Garmin's
  Cloudflare challenge where three fixes on top of `garmy` (User-Agent, TLS impersonation, login
  delay) did not. Logs showed the login chain's `mobile+cffi`/`mobile+requests` strategies
  returning `429` (IP rate-limited by Garmin, likely from repeated logins during this debugging
  process) and falling through to a later strategy that succeeded — expected behavior, no code
  change needed.
- **The MFA login web UI kept showing "not logged in" even after a real, successful login**:
  `python-garminconnect`'s `Garmin.login()`/`resume_login()` only persist the session to disk
  internally on the `return_on_mfa=False` code path — the MFA web UI and CLI bootstrap both
  require `return_on_mfa=True` (to detect an MFA requirement via a return value instead of an
  exception), so every login through either of them was silently never saved. `mfa_login.py` now
  persists the session itself right after a non-MFA success or a completed MFA resume.

## [0.1.0] - 2026-07-04

### Added
- Initial repository scaffolding: `CLAUDE.md`, `PROJECT_PLAN.md`, and the `stridesync/` add-on
  folder layout (`config.yaml`, `build.yaml`, `Dockerfile`, `rootfs/`, `DOCS.md`, `CHANGELOG.md`,
  icon/logo placeholders).
- Garmin Connect sync client (`app/sync/garmin_client.py`): authenticates via `garmy` and fetches
  recent activities merged with per-activity distance/pace/cadence detail and per-lap splits.
  All failures (bad credentials, MFA, broken SSO, network/proxy errors) surface as
  `GarminAuthError`/`GarminAPIError` instead of raw library exceptions.
- SQLite schema (`app/db/schema.sql`) for `activities`, `activity_metrics` (per-lap time series),
  and `sync_log`.
- Manual sync CLI: `python3 -m app.sync.scheduler --once` — logs in, syncs recent activities and
  laps, and records the outcome in `sync_log` whether it succeeds or fails.
- Unit test suite (`stridesync/tests/`, 22 tests) covering schema creation, Garmin API response
  normalization, and the sync/log-on-failure path, run with `pytest`.
- CI pipeline (`.github/workflows/ci.yml`): yamllint, hadolint, a `NEXT_VERSION`-vs-`config.yaml`
  version-ordering check, Python syntax check, `pytest`, and a Docker build smoke test on every
  push and PR, gated behind a single `CI Pass` required status check.
- Release pipeline (`.github/workflows/release.yml`, `workflow_dispatch`): tags
  `stridesync/NEXT_VERSION`, builds and pushes multi-arch (`amd64`/`aarch64`) images to GHCR,
  creates a GitHub release, and opens an automated post-release PR that stamps versions and
  updates both changelogs.
- `.yamllint.yml`, `.hadolint.yaml`, `.github/release.yml` (release-notes categorization), and
  `.github/dependabot.yml` (weekly pip/Docker/GitHub Actions update checks, security-only).
- Continuous sync scheduling (`app/sync/scheduler.py`'s `run_forever`): the sync-scheduler s6
  service now loops on `sync_interval_hours` instead of requiring manual `--once` invocation. A
  failed sync is logged and recorded in `sync_log` but never crashes the loop — the next
  scheduled interval is the retry. `SIGTERM`/`SIGINT` (sent by s6 on stop) now interrupt the wait
  promptly instead of blocking for up to `sync_interval_hours`.
- `rootfs/etc/services.d/sync-scheduler/run` now exports `garmin_username`, `garmin_password`,
  `sync_interval_hours`, and `log_level` from `bashio::config` as environment variables.
- MCP server (`app/mcp/server.py`), built directly on `fastmcp`: five tools —
  `recent_activities`, `activity_laps`, `pace_cadence_hr_trend`, `training_load_summary`, and
  `last_sync_status` — served over Streamable HTTP on `mcp_port` (default `8765`), reading the
  sync scheduler's SQLite DB through a read-only connection. Served natively by `fastmcp`
  (`transport="http"`) — no `mcp-proxy` process runs inside the add-on.
- `rootfs/etc/services.d/mcp-server/run` now exports `mcp_port`/`log_level` from `bashio::config`.

### Changed
- `icon.png`/`logo.png` replaced with a generated runner-glyph placeholder (correct dimensions,
  no longer a 1×1 scaffolding stub).
- `stridesync/config.yaml` now documents why no `ingress:` is declared (the add-on is API-only,
  with no browser-facing web UI panel).
- `README.md` rewritten: accurate status, a standalone Quick Start, install steps, config table,
  and the Garmin-auth known-risk note.

### Fixed
- `.github/workflows/release.yml`'s post-release changelog script: the very first release (no
  prior version section, no prior git tag) would have both generated a dead comparison link
  (`compare/v0.0.0...vX.Y.Z` — that tag was never created) and duplicated the version's
  reference-style link in the generated `stridesync/CHANGELOG.md`. Caught by simulating the
  script against this repo's real `CHANGELOG.md` before ever running it for real.

[Unreleased]: https://github.com/nsaputro/stride-sync/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/nsaputro/stride-sync/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/nsaputro/stride-sync/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/nsaputro/stride-sync/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/nsaputro/stride-sync/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/nsaputro/stride-sync/releases/tag/v0.1.0
