# Spec Delta

## MODIFIED Requirements

### Requirement: Garmin Workout Upload and Calendar Scheduling
The sync subsystem SHALL support uploading structured running workouts with optional sanitized descriptions and scheduling them to the athlete's Garmin Connect calendar.

#### Scenario: Successfully uploading and scheduling a workout
- **WHEN** a structured running workout and calendar date are submitted to the Garmin client
- **THEN** the client uploads the workout template, schedules it on the user's Garmin calendar, and returns the workout and schedule identifiers.

#### Scenario: Uploading workout with description
- **WHEN** a structured workout payload includes a workout description
- **THEN** the client includes the description truncated to 1,000 characters in the uploaded workout payload.

#### Scenario: Unscheduling and deleting a workout
- **WHEN** a scheduled workout identifier is deleted from the plan
- **THEN** the client removes the entry from the Garmin calendar and deletes the template from the Garmin workout library.
