# Proposal

## Why

The `schedule_garmin_workouts` MCP tool currently defines its input steps as untyped dictionaries, preventing AI agents from discovering valid step properties, targets, and repeat block formats. Providing strongly-typed Pydantic models for workout items and structured lap steps gives agents discoverable schemas and clear contracts.

## What Changes

- Define explicit Pydantic schemas for structured workout lap steps (`SingleStep`, `RepeatStep`), workout overrides (`WorkoutItem`), and tool outputs (`ScheduledWorkoutResult`, `DeleteOverrideResult`, `GearActionResult`).
- Update `schedule_garmin_workouts` tool parameters and return type to use Pydantic models, enabling FastMCP to generate complete JSON schema specifications for steps, durations, distances, pace targets, and HR zones.
- Enhance tool docstrings with complete field specifications and copy-pasteable JSON payload examples for single and repeat workouts.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `mcp-server`: Enrich `schedule_garmin_workouts` tool definition with strongly-typed schemas and detailed step specifications.

## Impact

- MCP clients and AI agents inspecting `schedule_garmin_workouts` receive full parameter and output schemas.
- Replaces internal dictionary parsing with Pydantic model attributes in `app/mcp/`.
