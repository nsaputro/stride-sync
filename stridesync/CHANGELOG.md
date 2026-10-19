# Changelog

## [0.9.5] - 2026-10-19

### Added
- Batch workout scheduling tool `schedule_garmin_workouts` to upload and schedule structured workouts with exact lap timing directly to Garmin Connect and connected Garmin watches.
- Support for structured step payloads and Garmin schedule identifiers in plan overrides storage.

### Changed
- Enforce pace (`pace.zone`) and heart rate (`heart.rate.zone`) target types for running workout steps uploaded to Garmin Connect, avoiding speed (`speed.zone`).

[0.9.5]: https://github.com/nsaputro/stride-sync/releases/tag/v0.9.5
