# Changelog

## [Unreleased]

### Added
- Pre-release/dev channel (install slug `stridesync_dev`, default host port `8766`) so fixes can
  be verified on a real HA instance before being promoted to a stable release.
- **Ingress web UI for the one-time Garmin MFA login**: a StrideSync panel now appears in the HA
  sidebar with a "Log in to Garmin Connect" button — an alternative to the `docker exec`-based
  CLI bootstrap (`python3 -m app.sync.bootstrap_login`) for users without terminal access.

### Fixed
- **The add-on failed to start in v0.1.0** (`ModuleNotFoundError: No module named 'app'`, both
  services) — a packaging bug, fixed. If you installed `v0.1.0`, update to this version.
- Fixed a related config-validation bug that would also have broken standalone (non-Supervisor)
  testing: the startup config check always reported Garmin credentials missing outside a real
  HA install, even when set correctly.
- Fixed a crash when any schema-validated option (`sync_interval_hours`, `mcp_port`,
  `log_level`) came through as the literal text `"null"` outside a real Supervisor — now falls
  back to the documented default instead.
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
- **The MFA login web UI's "Log in to Garmin Connect" button could return a bare "Internal
  Server Error"** instead of a clear message — it now handles network failures and other
  unexpected errors the same way the rest of the add-on does, always showing a diagnosable error
  page instead of crashing.

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

[0.1.0]: https://github.com/nsaputro/stride-sync/releases/tag/v0.1.0
