# Changelog

## [Unreleased]

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

## [0.4.1] - 2026-07-08

### Fixed
- **`planned_workouts` sync could still repeatedly delete-and-reinsert (and eventually lose)
  already-*completed* days** (milestone Stage 22, `planned_workouts` follow-up to Stage 18):
  reported live with a second real `taskList` response pasted a day after the first — confirmed
  `taskList` is actually a small rolling window (~7 days), not a fixed calendar week (it can
  straddle two `weekId`s), and each entry carries `taskWorkout.adaptiveCoachingWorkoutStatus`.
  A completed day (`"COMPLETED_TODAYS_WORKOUT"`) was still being treated as safe-to-replace, and
  once Garmin stopped returning it at all in a later response, its row was deleted with nothing
  to replace it. Only `"NOT_COMPLETE"` days are now added to `covered_dates`/replaced; completed
  days are left untouched, and a day with no `adaptiveCoachingWorkoutStatus` field falls back to
  the prior covered-window behavior.

[0.4.1]: https://github.com/nsaputro/stride-sync/releases/tag/v0.4.1
