## Why

Athletes and coaches need immediate visibility into upcoming scheduled workouts and plan overrides directly from the StrideSync web UI. Surfacing this merged schedule at the top of the Running tab enables quick comparison between Garmin default workouts and coach overrides with their rationales.

## What Changes

- Add upcoming training plan table at the top of the `/running` page (above Heart Rate Zones and Weekly Volume).
- Merge upcoming workouts from `planned_workouts` and `plan_overrides` for `workout_date >= CURRENT_DATE`.
- Display badges differentiating Garmin defaults and Coach Overrides, formatting targets, pace, heart rate, and coaching notes/rationales.
- Provide clean empty-state messaging when no upcoming workouts are scheduled.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `web-ui`: Extend the Running Analytics tab requirement to display upcoming scheduled workouts and active plan overrides at the top of the page.

## Impact

- Modifies `app/mfa_web/server.py` (`/running` endpoint, HTML rendering, CSS styles).
- Adds unit and integration tests in `tests/test_mfa_web_server.py`.
- No database schema or MCP protocol breaking changes.
