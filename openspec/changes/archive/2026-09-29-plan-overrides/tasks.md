## 1. Database Schema and Initialization

- [x] 1.1 Add `plan_overrides` table DDL and index to `app/db/schema.sql` and verify database initialization creates the table and index cleanly on both new and existing databases.

## 2. MCP Tools Implementation

- [x] 2.1 Implement `set_plan_override`, `get_plan_overrides`, and `delete_plan_override` in `app/mcp/server.py` with validation and writable connection handling, and verify with unit tests.
- [x] 2.2 Update `planned_vs_actual` in `app/mcp/server.py` to merge Garmin scheduled workouts with plan overrides and preserve original targets, verified by unit tests.

## 3. Tool Schemas and Test Suite

- [x] 3.1 Update lazy-loaded MCP tool schemas in `~/.gemini/antigravity-cli/mcp/stridesync/` for `set_plan_override`, `get_plan_overrides`, `delete_plan_override`, and `planned_vs_actual`.
- [x] 3.2 Add comprehensive unit tests in `tests/test_plan_overrides.py` covering CRUD and merge scenarios, and verify pytest and OpenSpec validation pass.

