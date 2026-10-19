# Spec Delta

## MODIFIED Requirements

### Requirement: Athlete Plan Overrides Storage
The data storage layer SHALL maintain athlete plan overrides in the `plan_overrides` table keyed by `workout_date` with target workout attributes, mandatory coaching rationale, optional execution notes, structured step definitions, remote Garmin workout and schedule identifiers, and created/updated timestamps.

#### Scenario: Storing workout plan override
- **WHEN** an override is saved for a calendar date
- **THEN** the record is stored or updated with the specified workout targets, reason, notes, and updated timestamp.

#### Scenario: Deleting workout plan override
- **WHEN** an override is deleted for a calendar date
- **THEN** the record is removed from `plan_overrides` while preserving existing synced planned workouts.

#### Scenario: Storing workout override with structured steps and Garmin identifiers
- **WHEN** an override record with structured lap steps and Garmin identifiers is inserted or updated
- **THEN** the storage layer persists the step definitions and identifiers alongside standard target metrics.
