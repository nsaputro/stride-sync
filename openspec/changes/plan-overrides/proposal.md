## Why

Athletes and coaches need to adjust or override Garmin Connect's default adaptive workouts (e.g. taper volume adjustments, workout substitutions, or recovery changes) while tracking the coaching rationale across syncs. Adding plan overrides enables overriding workouts and viewing original versus overridden plans side-by-side with reasons in MCP.

## What Changes

- **Plan Overrides Storage**: Add persistent storage for planned workout overrides keyed by calendar date, including workout attributes, mandatory coaching rationale, optional execution notes, and timestamps.
- **Override Management MCP Tools**: Expose `set_plan_override` to create/update overrides, `get_plan_overrides` to query active overrides in a date window, and `delete_plan_override` to revert to Garmin's plan.
- **Enhanced Planned vs. Actual Tool**: Update `planned_vs_actual` to merge Garmin planned workouts with plan overrides, surfacing override flags, reasons, notes, and original Garmin targets.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `data-storage`: Add persistent storage requirement for athlete plan overrides with workout attributes, rationale, notes, and timestamps.
- `mcp-server`: Add requirements for plan override management tools (`set_plan_override`, `get_plan_overrides`, `delete_plan_override`) and enhanced `planned_vs_actual` comparison merging overrides.

## Impact

- Schema: New `plan_overrides` table and index in SQLite database.
- MCP Server: Three new tools (`set_plan_override`, `get_plan_overrides`, `delete_plan_override`) and updated response schema for `planned_vs_actual`.
- Client Tool Definitions: Updated MCP tool schemas for lazy loading.
