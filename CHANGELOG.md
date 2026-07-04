# Changelog

All notable changes to StrideSync are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions match `stridesync/config.yaml` and the GitHub release tags.

---

## [Unreleased]

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

[Unreleased]: https://github.com/nsaputro/stride-sync/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nsaputro/stride-sync/releases/tag/v0.1.0
