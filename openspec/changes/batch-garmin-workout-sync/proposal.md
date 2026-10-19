# Proposal

## Why
Athletes and AI coaches need to schedule multi-day training plans with structured lap/interval timings and push them directly to Garmin Connect so workouts automatically sync down to the runner's Garmin watch. Currently, overrides are limited to single-day flat averages stored only in local SQLite without watch synchronization.

## What Changes
- Expose a new MCP tool `schedule_garmin_workouts` to batch-schedule workouts with step-by-step lap structures (warmup, repeats, pace/HR targets, recovery, cooldown) and push them to Garmin Connect.
- Support syncing scheduled workouts to Garmin Connect calendar so they download directly to connected Garmin watches.
- Update `delete_plan_override` to unschedule and delete the workout from Garmin Connect when a remote workout/schedule reference exists.
- Extend `get_plan_overrides` and `planned_vs_actual` to return structured lap steps and Garmin sync status.
- Store structured step payloads and Garmin workout/schedule identifiers in the persistent plan overrides store.

## Capabilities

### Modified Capabilities
- `mcp-server`: Expose `schedule_garmin_workouts` batch tool and update `delete_plan_override`, `get_plan_overrides`, and `planned_vs_actual` with structured lap steps and Garmin sync management.
- `garmin-sync`: Add workout creation, calendar scheduling, and calendar unscheduling write-back operations.
- `data-storage`: Extend plan overrides storage with structured steps and Garmin workout and schedule identifiers.

## Impact
- Local SQLite database schema (`plan_overrides` table).
- Garmin client API wrapper (adding workout upload and calendar scheduling).
- MCP tool suite for training plan overrides.
- No breaking changes to existing read tools.
