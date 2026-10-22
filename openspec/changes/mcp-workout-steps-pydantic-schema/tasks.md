# Tasks

## 1. Schema Definition & Tool Implementation

- [x] 1.1 Create `stridesync/app/mcp/schemas.py` defining Pydantic models for workout steps, workout requests, and MCP tool responses, verifying parsing with unit tests.
- [x] 1.2 Update `schedule_garmin_workouts` and plan override handlers in `stridesync/app/mcp/server.py` to use Pydantic models and direct attribute access, verifying Python AST syntax check.
- [x] 1.3 Enrich `schedule_garmin_workouts` docstrings with full property descriptions and example JSON payloads, verifying schema introspection via FastMCP `list_tools()`.

## 2. Validation & Testing

- [x] 2.1 Update and expand `stridesync/tests/test_plan_overrides.py` and `stridesync/tests/test_mcp_server.py` for typed step schemas and repeat interval blocks, verifying with `pytest`.
- [x] 2.2 Update changelog entries in root `CHANGELOG.md` and add-on `stridesync/CHANGELOG.md`, verifying with `openspec validate --all --strict`.
