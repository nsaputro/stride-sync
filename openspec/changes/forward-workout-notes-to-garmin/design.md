# Design

## Context
- See [proposal.md](proposal.md) for background and motivation.
- Upstream `python-garminconnect`'s `RunningWorkout` already provides an optional `description` attribute in its wire dictionary model.

## Goals / Non-Goals
**Goals:**
- Forward `WorkoutItem.notes` (or fallback rationale) to Garmin Connect's workout description field.
- Sanitize and limit description string length to protect against upstream Garmin Connect API rejection.

**Non-Goals:**
- Changing database schema or altering how notes and rationales are stored in SQLite `plan_overrides`.
- Modifying single-workout override tools (`set_plan_override`).

## Decisions
- **Option A Fallback Logic**: Use `WorkoutItem.notes` when non-empty, falling back to `f"Reason: {item.reason}"` when notes is omitted, keeping descriptions clean without redundant prefixing when explicit notes are supplied.
- **Payload Builder Parameter**: Add `description: Optional[str] = None` directly to `build_running_workout_payload` and `GarminClient.upload_running_workout` to keep payload construction encapsulated within the Garmin client wrapper.
- **1,000-Character Boundary**: Truncate description at 1,000 characters before passing into `RunningWorkout` to prevent remote API rejection while preserving comprehensive coaching cues.

## Risks / Trade-offs
- [Overly long notes or multiline prompts exceed Garmin limits] → Explicit 1,000-character truncation in `build_running_workout_payload` ensures payloads never trigger HTTP 400 Bad Request.
