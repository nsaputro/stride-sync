# Spec Delta

## ADDED Requirements

### Requirement: Batch Garmin Workout Scheduling MCP Tool
The server SHALL expose a `schedule_garmin_workouts` MCP tool that accepts a batch list of workout overrides with structured lap steps, schedules them to Garmin Connect, and records them locally.

#### Scenario: Batch scheduling valid workouts
- **WHEN** an agent invokes `schedule_garmin_workouts` with one or more valid workout plans and coaching rationales
- **THEN** the server uploads and schedules each workout to Garmin Connect, stores the records in local plan overrides, and returns the list of scheduled summaries.

#### Scenario: Batch scheduling rejection on invalid inputs
- **WHEN** an agent invokes `schedule_garmin_workouts` with missing required attributes or empty coaching rationale
- **THEN** the tool call fails with a validation error without scheduling remote workouts.

## MODIFIED Requirements

### Requirement: Plan Overrides Management MCP Tools
The server SHALL expose MCP tools `set_plan_override`, `get_plan_overrides`, and `delete_plan_override` to manage athlete workout modifications with required rationale tracking, structured lap steps, and remote Garmin calendar unscheduling.

#### Scenario: Creating or updating plan override
- **WHEN** an agent invokes `set_plan_override` with valid date, workout attributes, and non-empty reason
- **THEN** the server persists the override record and returns the saved override dictionary.

#### Scenario: Listing active plan overrides
- **WHEN** an agent invokes `get_plan_overrides` for a date range or lookback window
- **THEN** the server returns active overrides sorted ascending by workout date.

#### Scenario: Deleting a plan override
- **WHEN** an agent invokes `delete_plan_override` for an existing override date
- **THEN** the server deletes the override and returns confirmation status.

#### Scenario: Deleting a plan override with remote Garmin schedule
- **WHEN** an agent invokes `delete_plan_override` for an override containing a Garmin schedule identifier
- **THEN** the server unschedules the workout from Garmin Connect and removes the local override record.
