# Tasks

## 1. Garmin Workout Payload Builder & Client

- [x] 1.1 Add optional description parameter to `build_running_workout_payload` and `upload_running_workout` with 1,000-character sanitization and verify with unit tests in `tests/test_garmin_client.py`

## 2. MCP Server Forwarding & Documentation

- [x] 2.1 Update `schedule_garmin_workouts_direct` in `stridesync/app/mcp/server.py` to forward workout notes (or fallback rationale) to `client.upload_running_workout` and verify with unit tests in `tests/test_plan_overrides.py`
- [x] 2.2 Update documentation in `README.md` and `stridesync/DOCS.md` describing workout notes forwarding to Garmin Connect and verify formatting consistency
