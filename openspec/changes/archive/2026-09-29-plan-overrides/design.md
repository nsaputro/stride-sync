## Context

See [proposal.md](file:///home/nsaputro-agent/gitspace/stride-sync/openspec/changes/plan-overrides/proposal.md). StrideSync separates read-only MCP queries from scheduler write operations using SQLite WAL mode.

## Goals / Non-Goals

**Goals:**
- Provide atomic upsert and deletion for calendar-date plan overrides.
- Merge plan overrides with Garmin's scheduled workouts seamlessly in `planned_vs_actual`.

**Non-Goals:**
- Syncing user overrides back to Garmin Connect's proprietary training plan cloud API.
- Multi-user override partitioning (out of scope for single-user add-on).

## Decisions

- **Single override per calendar date (`workout_date PRIMARY KEY`)**: Matches Garmin's single primary daily workout model and simplifies idempotent upserts.
- **Dedicated `_connect_write` connection helper**: Isolates write operations for `set_plan_override` and `delete_plan_override` with 5000ms busy timeout without altering `_connect_readonly`.
- **Date union CTE query for `planned_vs_actual`**: Unifies distinct dates from `planned_workouts` and `plan_overrides` so overrides on days without a Garmin workout appear alongside days with Garmin workouts.
- **Preserve original Garmin targets**: Include `garmin_planned_*` fields when `is_overridden: true` to give AI agents full side-by-side visibility into adaptations.

## Risks / Trade-offs

- **[Concurrent write contention]** → SQLite WAL mode with 5-second busy timeout prevents lock collisions between sync scheduler and MCP writes.
- **[Overriding days with multiple Garmin workouts]** → Garmin plans typically schedule at most one daily workout; joining on `workout_date` gracefully preserves per-date override precedence.
