# Tasks

## 1. Storage & Schema Migration

- [x] 1.1 Add `garmin_workout_id`, `garmin_schedule_id`, and `steps_json` columns to `plan_overrides` table in `schema.sql` and verify migration in `tests/test_db.py`.

## 2. Garmin Client Workout Upload & Scheduling

- [x] 2.1 Implement `upload_running_workout`, `schedule_workout`, `unschedule_workout`, and `delete_workout` on `GarminClient` and verify step serialization and API error handling in `tests/test_garmin_client.py`.

## 3. MCP Tools Implementation

- [x] 3.1 Implement `schedule_garmin_workouts` MCP tool and update `delete_plan_override` to unschedule remote workouts, verifying execution in `tests/test_plan_overrides.py`.
- [x] 3.2 Update `get_plan_overrides` and `planned_vs_actual` to parse and return structured steps and Garmin sync identifiers, verifying tool payloads in `tests/test_mcp_server.py`.

## 4. Test Suite & Spec Validation

- [x] 4.1 Run the complete test suite with `pytest` and execute strict OpenSpec validation to confirm requirements compliance.

## 5. Dev Release Deployment & End-to-End Testing

- [x] 5.1 Bump `stridesync-dev/config.yaml` version tracking `{NEXT_VERSION}b{N}` and verify Docker packaging checks in CI.
- [ ] 5.2 Deploy the dev channel release to Home Assistant and execute end-to-end MCP integration tests against the live MCP server to verify batch workout scheduling on Garmin Connect.
