# Changelog

## [0.6.0] - 2026-07-14

### Added
- **Real training load (CTL/ATL/TSB/ACWR) in `daily_wellness`** (milestone Stage 26): four new
  columns — `acute_training_load`, `chronic_training_load`, `training_stress_balance` (derived
  locally as chronic − acute), and `acute_chronic_workload_ratio` (Garmin's own value) — sourced
  from the same `get_training_status` call `daily_wellness` already makes, no extra API cost.
  Also fixes `training_status_label` to prefer a more authoritative nested response path
  (confirmed via reviewing another Garmin Connect MCP project built on the same underlying
  library), falling back to the original guess unchanged if that path isn't present.
- **Body Battery, stress, and respiration in `daily_wellness`** (milestone Stage 27): six new
  columns — `body_battery_charged`/`body_battery_drained`, `stress_avg`/`stress_max`,
  `respiration_waking_avg`/`respiration_sleep_avg` — three more independently-fetched recovery
  signals alongside the existing sleep/HRV/readiness/resting-HR fields. Body Battery's headline
  0-100 level isn't included yet; only `charged`/`drained` are confirmed field names.
- **Shoe/gear mileage tracking** (milestone Stage 28): new `gear` table + `gear_mileage` MCP
  tool — cumulative distance/activity counts per tracked gear item (shoes, bikes, etc.), most-used
  first, for replacement-timing tracking. Returns `[]` for an account with no gear configured,
  not an error. A genuinely new running-specific capability, not present in any form before.
- **Write-back gear correction** (milestone Stage 29): new `activity_gear` (read),
  `add_activity_gear`, and `remove_activity_gear` (write) MCP tools, letting a user correct
  which shoe/gear is assigned to a run directly in Garmin Connect. This is StrideSync's
  **first-ever write-back to Garmin** — every prior tool only ever reads. The two write tools
  require the calling model to have gotten explicit user confirmation for each specific
  correction before calling them; StrideSync itself was, until now, entirely read-only, and that
  claim throughout the repo's docs (`README.md`, `stridesync/DOCS.md`, `PROJECT_PLAN.md`) has
  been updated to reflect the new, narrow exception.
- **On-demand sync: `sync_now` MCP tool** (milestone Stage 30): triggers a fresh sync
  immediately (the same `run_sync_once` the scheduled sync-scheduler service's timer calls) and
  returns the resulting sync status, so a question about a run that may have just finished can be
  answered accurately without waiting for the next scheduled sync window (default every 6h).
  `docs/skills/running-coach/SKILL.md` updated with guidance on when to call it (a likely-just-
  finished run) versus when not to (trend/historical questions, where it's unnecessary overhead).

[0.6.0]: https://github.com/nsaputro/stride-sync/releases/tag/v0.6.0
