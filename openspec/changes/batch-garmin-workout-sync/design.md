# Design

## Context
See [proposal.md](proposal.md). StrideSync isolates Garmin API interactions in `GarminClient` and uses SQLite for local state.

## Goals / Non-Goals
**Goals:**
- Translate structured running workout steps into Garmin Connect workout structures via `garminconnect.workout`.
- Upload and schedule workouts on Garmin Connect calendar, tracking remote identifiers in `plan_overrides`.
- Remove remote Garmin workouts and schedules when an override is deleted via MCP.

**Non-Goals:**
- Direct local Bluetooth or USB communication with watches (sync occurs via Garmin Connect cloud).
- Non-running sports (cycling, swimming, multisport).

## Decisions
- **GarminClient write encapsulation**: House all `garminconnect.workout` model mapping and calendar schedule calls in `app/sync/garmin_client.py` to preserve client boundary isolation.
- **JSON step storage in SQLite**: Store structured workout steps as JSON (`steps_json`) in `plan_overrides` to support variable interval and repeat hierarchies without fragile schema changes.
- **Remote cleanup on deletion**: Trigger Garmin unschedule and workout removal when `delete_plan_override` is invoked on an override containing Garmin identifiers.
- **Fail-loud write errors**: Raise structured errors on network, auth, or schema failures during workout creation to prevent partial state drift.

## Risks / Trade-offs
- [Garmin rate limits or throttling] → Process batch uploads sequentially with fail-safe error handling.
- [Session expiration during upload] → Leverage existing session recovery in `GarminClient` and raise clear `GarminAPIError` diagnostics if reauth fails.
