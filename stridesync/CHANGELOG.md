# Changelog

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
