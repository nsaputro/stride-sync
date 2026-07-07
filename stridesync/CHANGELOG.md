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
