## ADDED Requirements

### Requirement: Plan Overrides Management MCP Tools
The server SHALL expose MCP tools `set_plan_override`, `get_plan_overrides`, and `delete_plan_override` to manage athlete workout modifications with required rationale tracking.

#### Scenario: Creating or updating plan override
- **WHEN** an agent invokes `set_plan_override` with valid date, workout attributes, and non-empty reason
- **THEN** the server persists the override record and returns the saved override dictionary.

#### Scenario: Listing active plan overrides
- **WHEN** an agent invokes `get_plan_overrides` for a date range or lookback window
- **THEN** the server returns active overrides sorted ascending by workout date.

#### Scenario: Deleting a plan override
- **WHEN** an agent invokes `delete_plan_override` for an existing override date
- **THEN** the server deletes the override and returns confirmation status.

### Requirement: Planned vs Actual Workout Comparison MCP Tool
The server SHALL expose the `planned_vs_actual` MCP tool comparing scheduled workouts against logged activities, merging any active plan overrides and surfacing rationale.

#### Scenario: Querying planned versus actual with overrides
- **WHEN** an agent calls `planned_vs_actual` for a date window containing overrides
- **THEN** each date returns merged workout targets with `is_overridden: true`, `override_reason`, and original Garmin plan targets preserved.

#### Scenario: Querying planned versus actual without overrides
- **WHEN** an agent calls `planned_vs_actual` for a date window without overrides
- **THEN** scheduled workouts are returned with `is_overridden: false` and `override_reason: null`.
