# Design

## Context
See [proposal.md](proposal.md) for motivation. FastMCP 3.4 automatically derives OpenAPI JSON schemas and output schemas from Pydantic model type annotations.

## Goals / Non-Goals
**Goals:**
- Provide discoverable, strictly-typed schemas for workout items and structured lap steps in MCP tools.
- Replace manual dictionary parsing and duck typing in `batch_schedule_workouts` with Pydantic model attribute access.

**Non-Goals:**
- Modifying underlying SQLite schema in `plan_overrides`.
- Rewriting Garmin Connect REST client payloads in `garmin_client.py` (models dump to dictionaries for wire upload).

## Decisions
- **Dedicated Schema Module (`app/mcp/schemas.py`)**: Centralizes `SingleStep`, `RepeatStep`, `WorkoutStep`, `WorkoutItem`, and output models to isolate data contracts from server routing.
- **Discriminated Union for WorkoutStep**: `SingleStep` and `RepeatStep` differentiate automatically via `step_type` and required fields (`repeats`), allowing clean JSON Schema generation by FastMCP without schema collisions.
- **Pure Pydantic Contracts**: Avoid legacy dictionary compatibility wrappers in `batch_schedule_workouts`; tool callers provide typed payloads and internal code accesses model fields directly.
- **Model Dump at API Boundary**: Convert validated `WorkoutStep` instances to dictionaries via `model_dump(exclude_unset=True)` right before calling `garmin_client.upload_running_workout` and saving `steps_json`.

## Risks / Trade-offs
- [Strict payload validation rejects malformed steps] → Clear Pydantic error details surface directly to calling MCP clients so agents can self-correct.
