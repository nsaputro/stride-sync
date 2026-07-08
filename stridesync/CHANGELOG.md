# Changelog

## [Unreleased]

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

## [0.3.3] - 2026-07-08

### Added
- **Example Claude Skill: `docs/skills/running-coach/`** (milestone Stage 9 follow-up): a
  `SKILL.md` that turns StrideSync's raw MCP tools into a structured running-coaching
  workflow — race-target tracking, training-progression checks (weekly load, long-run/mileage
  trends, recovery/readiness cross-referencing), target-pace/HR lookups, and lap-level analysis
  that separates structured-workout work-rep pace from recovery-jog pace instead of a misleading
  whole-session average. `docs/skills/README.md` explains what a Skill is and how to install
  one. Purely additive documentation — no application code changed, entirely optional to use.

### Fixed
- **`planned_workouts` sync could silently wipe out already-synced future/past weeks**
  (milestone Stage 18 follow-up): reported live with the full real `taskList` response pasted —
  all 7 entries share one `weekId` (34). Neither `get_training_plan_by_id` nor
  `get_adaptive_training_plan_by_id` takes a date-range argument at all; each call always
  returns just the plan's *current* week, regardless of the sync's `±14`-day requested window.
  `_replace_planned_workouts` used to DELETE the entire requested window every sync but only
  ever re-INSERT the one week Garmin actually returned, silently wiping any other week's rows
  with nothing to replace them. Fixed by scoping the DELETE to exactly the calendar dates a
  fetch actually covered (`covered_dates`, including rest-day dates), not the full requested
  window. A confirmed-empty plan list (no active plan) still clears the whole window, since
  that's a complete answer; a transient fetch failure now touches nothing at all, instead of
  wiping existing data on a network blip.

[0.3.3]: https://github.com/nsaputro/stride-sync/releases/tag/v0.3.3
