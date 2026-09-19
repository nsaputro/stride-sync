## Purpose

Tracks equipment and shoe mileage and enables write-back gear assignment and correction to Garmin Connect with explicit human-in-the-loop confirmation.

## Requirements

### Requirement: Gear Mileage Tracking
The system SHALL sync gear items from Garmin Connect and expose cumulative distance and usage via the `gear_mileage` MCP tool.

#### Scenario: Querying gear usage
- **WHEN** an agent calls `gear_mileage`
- **THEN** the server returns tracked shoes and gear items sorted by cumulative distance descending.

### Requirement: Live Activity Gear Inspection
The system SHALL query Garmin Connect live via `activity_gear` to return the gear items currently associated with a specific activity.

#### Scenario: Inspecting activity gear
- **WHEN** an agent calls `activity_gear` with an `activity_id`
- **THEN** the server queries Garmin Connect directly and returns the list of assigned gear items.

### Requirement: Human-Confirmed Write-Back Modifications
The MCP server SHALL expose `add_activity_gear` and `remove_activity_gear` tools that write changes directly to Garmin Connect, and their contract SHALL mandate prior human user confirmation before invocation.

#### Scenario: Assigning gear to an activity
- **WHEN** a user explicitly confirms assigning a gear item and the agent invokes `add_activity_gear`
- **THEN** the server calls Garmin Connect's gear assignment API and returns the updated gear status.

#### Scenario: Removing gear from an activity
- **WHEN** a user explicitly confirms unassigning a gear item and the agent invokes `remove_activity_gear`
- **THEN** the server calls Garmin Connect's gear removal API and returns confirmation of removal.
