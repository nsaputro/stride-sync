# Changelog

## [Unreleased]

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

## [0.4.0] - 2026-07-08

### Changed
- **Web UI redesign: typographic hierarchy, boxed cards, login moved to Settings** (milestone
  Stage 20): the Dashboard's four "Total X synced" lines are now a 2×2 grid of boxed stat tiles,
  "Recent activities" (and the Running tab's weekly mileage) are now individual rounded rows
  instead of a hairline-bordered list, and text now follows an actual type scale instead of one
  weight/size for nearly everything — all lifted from a Garmin Connect Personal-Records
  screenshot given as a design reference, and shared as an Artifact mockup for approval before
  any code changed. Garmin Connect login status/controls moved off the Dashboard entirely onto
  the Settings tab (a new "Account" card); the Dashboard now just shows a brief "not connected"
  notice with a link to Settings when there's no session.

[0.4.0]: https://github.com/nsaputro/stride-sync/releases/tag/v0.4.0
