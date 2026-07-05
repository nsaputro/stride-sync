# Changelog

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

[0.2.1]: https://github.com/nsaputro/stride-sync/releases/tag/v0.2.1
