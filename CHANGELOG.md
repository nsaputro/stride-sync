# Changelog

All notable changes to StrideSync are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions match `stridesync/config.yaml` and the GitHub release tags.

---

## [Unreleased]

### Added
- OpenSpec spec-driven development support with baseline capability specs and Antigravity workflows.
- Pre-release dev channel end-to-end testing workflow documented in `AGENTS.md`.

### Fixed
- Pinned `fastmcp>=3.4.0,<4.0.0` to prevent upstream FastMCP 4.x breaking changes.

## [0.9.0] - 2026-08-12

### Added
- Path-embedded authentication token support (`/mcp/<token>`) for clients that cannot set custom HTTP headers.

## [0.8.1] - 2026-08-11

### Fixed
- Serve server icon via `/favicon.ico` for clients that fetch icons via standard HTTP paths.

## [0.8.0] - 2026-08-11

### Added
- Declare MCP server connector icon via `Implementation.icons` metadata.
- Short-burst sprint session guidance in `running-coach` example skill.

### Fixed
- Ensure `icon.png` is packaged inside container image.

## [0.7.0] - 2026-07-28

### Added
- Unauthenticated `/health` endpoint reporting server status and registered MCP tools.
- Heart rate zone ranges (Zone 1-5 bpm) on the web UI Running tab.

## [0.6.0] - 2026-07-14

### Added
- Training load metrics (`acute_training_load`, `chronic_training_load`, `training_stress_balance`, `acute_chronic_workload_ratio`) in `daily_wellness`.
- Body Battery, stress, and respiration metrics in `daily_wellness`.
- Shoe and gear mileage tracking (`gear_mileage` tool and `gear` table).
- Write-back gear correction tools (`activity_gear`, `add_activity_gear`, `remove_activity_gear`) with explicit human confirmation.
- On-demand synchronization via `sync_now` MCP tool.

## [0.5.0] - 2026-07-13

### Added
- `search_activities` MCP tool to filter activities by date, type, or distance.
- Charting conventions and race-distance performance comparison in `running-coach` skill.

## [0.4.1] - 2026-07-08

### Fixed
- Scoped `planned_workouts` replacement to only uncompleted days, preserving completed workout history.

## [0.4.0] - 2026-07-08

### Changed
- Redesigned web UI with card layout, typographic hierarchy, and account settings view.

## [0.3.3] - 2026-07-08

### Added
- Example `running-coach` Claude Skill for race planning and workout analysis.

### Fixed
- Scoped `planned_workouts` delete/replace logic to covered dates only, preventing accidental plan wipes.

## [0.3.2] - 2026-07-07

### Fixed
- Fixed VO2 max and fitness age response unwrapping from Garmin API.

## [0.3.1] - 2026-07-07

### Added
- Diagnostics panel in Settings tab for raw API response inspection.
- Total wellness, VO2 max, and workout sync counters on Dashboard.

### Fixed
- Reduced log level for missing VO2 max date estimates from WARNING to DEBUG.

## [0.3.0] - 2026-07-07

### Added
- Daily wellness sync (`daily_wellness`, `resting_hr_trend`).
- VO2 max trend sync (`vo2max_trend`).
- Training plan sync (`planned_vs_actual`).
- Diagnostics panel in Settings tab.

### Changed
- Scheduled sync now fetches activities incrementally from last successful sync date.
- Added per-record-type sync summary logging.
- Extended backfill to include wellness and VO2 max data with regular sync parity.

### Fixed
- Handled non-dict response shapes in VO2 max normalization.
- Prevented backfill loop with Post/Redirect/Get pattern.
- Fixed plan ID and task list field parsing in Garmin training plans.

## [0.2.2] - 2026-07-05

### Added
- Per-activity ambient temperature time series in `activity_samples`.

### Changed
- Updated documentation for Claude connection over LAN and Cloudflare Tunnel.

### Fixed
- Fixed re-login flow for accounts with active MFA sessions.

## [0.2.1] - 2026-07-05

### Added
- Settings tab with one-off historical activity backfill and live progress bar.

### Fixed
- Switched SQLite to WAL mode with 5s busy timeout to resolve database lock errors during backfills.
- Preserved backfill progress bar state across web UI tab switches.

## [0.2.0] - 2026-07-05

### Added
- Dev channel add-on (`stridesync_dev`) and pre-release GitHub Actions workflow.
- Docker container runtime smoke test in CI.
- Ingress web UI for Garmin MFA login, manual sync, and recent activity dashboard.
- Physiological metrics: `training_baseline`, `activity_hr_zones`, and `activity_samples`.
- Optional bearer token authentication (`mcp_auth_token`) for MCP server.
- Weekly mileage summary on web UI Running tab.

### Fixed
- Fixed container package directory structure (`COPY app/ ./app/`).
- Fixed standalone option validation when running outside Home Assistant Supervisor.
- Migrated Garmin auth client to `python-garminconnect` to resolve Cloudflare challenges.
- Handled MFA challenge gracefully with session caching and `.mfa_required` fast-fail marker.
- Handled transport errors in web UI login flow.

## [0.1.0] - 2026-07-04

### Added
- Initial add-on scaffolding, supervisor configuration, and s6-overlay service management.
- Garmin Connect sync client and SQLite storage for activities, laps, and sync logs.
- FastMCP server over Streamable HTTP exposing 5 core tools.
- CI and release automation pipelines.

[Unreleased]: https://github.com/nsaputro/stride-sync/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/nsaputro/stride-sync/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/nsaputro/stride-sync/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/nsaputro/stride-sync/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/nsaputro/stride-sync/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/nsaputro/stride-sync/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/nsaputro/stride-sync/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/nsaputro/stride-sync/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/nsaputro/stride-sync/compare/v0.3.3...v0.4.0
[0.3.3]: https://github.com/nsaputro/stride-sync/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/nsaputro/stride-sync/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/nsaputro/stride-sync/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/nsaputro/stride-sync/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/nsaputro/stride-sync/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/nsaputro/stride-sync/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/nsaputro/stride-sync/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/nsaputro/stride-sync/releases/tag/v0.1.0
