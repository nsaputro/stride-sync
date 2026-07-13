# Changelog

## [Unreleased]

### Added
- **Real training load (CTL/ATL/TSB/ACWR) in `daily_wellness`** (milestone Stage 26): four new
  columns — `acute_training_load`, `chronic_training_load`, `training_stress_balance` (derived
  locally as chronic − acute), and `acute_chronic_workload_ratio` (Garmin's own value) — sourced
  from the same `get_training_status` call `daily_wellness` already makes, no extra API cost.
  Also fixes `training_status_label` to prefer a more authoritative nested response path
  (confirmed via reviewing another Garmin Connect MCP project built on the same underlying
  library), falling back to the original guess unchanged if that path isn't present.

## [0.5.0] - 2026-07-13

### Added
- **`running-coach` example skill: charting conventions for pace/HR over time** (milestone Stage
  23, `docs/skills/running-coach/SKILL.md` follow-up): a new section giving concrete conventions
  for visualizing `activity_samples` pace/HR time series — high point density, a numeric x-axis
  extended to the run's true finish, pace in flipped min/km (faster at top, matching Garmin), GPS
  dropout clipping, and two stacked charts (pace, HR) instead of one scaled single-axis overlay,
  since the chart tool has no second y-axis. Purely additive documentation — no application code
  changed.
- **New MCP tool: `search_activities`** (milestone Stage 24): find activities by an optional
  date range, activity type (case-insensitive), and/or distance range, newest first — combines
  all given filters with AND, and behaves exactly like `recent_activities` with none set. Fills
  the gap where `recent_activities`' only lever was "most recent N," with no way to look up e.g.
  "runs over 20km in June" without pulling a large limit and filtering client-side.
- **`running-coach` example skill: race-distance performance comparison** (milestone Stage 25,
  `search_activities` follow-up): a new section for finding and comparing a runner's history at
  a specific race distance (10K, half marathon, marathon) using distance-band searches, comparing
  pace alongside HR to distinguish genuine fitness gains from harder efforts, and pulling
  `activity_laps` for pacing-strategy detail on standout results. Purely additive documentation —
  no application code changed.

[0.5.0]: https://github.com/nsaputro/stride-sync/releases/tag/v0.5.0
