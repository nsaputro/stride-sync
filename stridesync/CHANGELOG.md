# Changelog

## [Unreleased]

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

## [0.3.2] - 2026-07-07

### Fixed
- **`vo2max_history` silently syncing rows with every field `NULL`, despite the account having
  real VO2 max history in the Garmin Connect app** (milestone Stage 12 follow-up): the "list
  means unexpected shape, degrade to no data" guard added in `0.3.1` was itself the bug —
  `get_max_metrics`'s real successful response is a list containing one dict
  (`[{"generic": {...}, ...}]`), not a bare dict, so that guard was silently discarding every
  real response instead of only the genuinely-empty ones. `_normalize_vo2max` now unwraps that
  list before extracting fields, confirmed against a real account's Diagnostics panel output
  (`vo2MaxPreciseValue: 55.2`). Also fixed `fitnessAge`, which actually lives nested under
  `generic`, not at the top level as originally guessed.

[0.3.2]: https://github.com/nsaputro/stride-sync/releases/tag/v0.3.2
