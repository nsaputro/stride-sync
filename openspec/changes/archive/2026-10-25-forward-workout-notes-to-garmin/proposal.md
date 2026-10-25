# Proposal

## Why

Athletes and coaches scheduling workouts via MCP cannot see execution notes or override rationales on Garmin Connect because the description field is not forwarded in the upload payload. Populating Garmin Connect's workout description from scheduled notes provides critical coaching cues and pacing instructions on athlete devices.

## What Changes

- Forward workout notes into the Garmin Connect workout description payload when scheduling workouts via MCP.
- Fall back to the coaching rationale prefixed with "Reason: " when notes are omitted.
- Sanitize and constrain description text length to 1,000 characters to prevent remote API rejection.
- Preserve existing local storage and scheduling behavior in SQLite and calendar endpoints.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `mcp-server`: Update batch workout scheduling requirement to forward notes and coaching rationale into Garmin workout description payloads.
- `garmin-sync`: Update workout upload requirement to support optional workout description strings.

## Impact

- MCP `schedule_garmin_workouts` tool now populates workout descriptions on Garmin Connect.
- No breaking changes to existing MCP schemas or stored database records.
