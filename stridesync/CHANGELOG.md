# Changelog

All notable changes to the StrideSync add-on are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions match `config.yaml` and the GitHub release tags.

---

## [Unreleased]

### Added
- Garmin Connect sync client, SQLite schema, and a manual sync CLI
  (`python3 -m app.sync.scheduler --once`) for verifying auth and the data model against a real
  Garmin account.
- CI (lint, syntax check, tests, Docker build smoke test) and release (multi-arch GHCR images,
  GitHub release, automated post-release version bump) pipelines.
- The sync-scheduler service now runs continuously, polling Garmin Connect every
  `sync_interval_hours` (default 6) instead of requiring a manual sync. Stops promptly when the
  add-on is stopped/restarted instead of blocking for up to `sync_interval_hours`.
- MCP server: query your synced activities from Claude or any MCP client over Streamable HTTP on
  `mcp_port` (default `8765`/`/mcp`) — recent activities, per-lap splits, pace/cadence/HR trends,
  training load summaries, and last-sync status.
- Add-on icon and logo.

### Changed
- No ingress panel — StrideSync is API-only (sync scheduler + MCP server), reachable directly
  over the network rather than through the HA sidebar.
