# Spec Delta

## MODIFIED Requirements

### Requirement: Batch Garmin Workout Scheduling MCP Tool
The server SHALL expose a `schedule_garmin_workouts` MCP tool that accepts a batch list of structured workout overrides with typed lap steps, schedules them to Garmin Connect, and records them locally.

#### Scenario: Batch scheduling valid workouts
- **WHEN** an agent invokes `schedule_garmin_workouts` with one or more valid workout plans and coaching rationales
- **THEN** the server uploads and schedules each workout to Garmin Connect, stores the records in local plan overrides, and returns the list of scheduled summaries.

#### Scenario: Batch scheduling rejection on invalid inputs
- **WHEN** an agent invokes `schedule_garmin_workouts` with missing required attributes or empty coaching rationale
- **THEN** the tool call fails with a validation error without scheduling remote workouts.

#### Scenario: Tool schema introspection
- **WHEN** an MCP client or agent inspects the tool schema for `schedule_garmin_workouts`
- **THEN** the schema defines typed properties for step types, durations, distances, target pace, target heart rate, and repeat groups.
