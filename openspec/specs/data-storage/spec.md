## Purpose

Manages the persistent SQLite database, structured relational schemas, automated startup migrations, and data consistency for all synced Garmin running and physiological records.

## Requirements

### Requirement: Database Initialization and Migration
The data storage layer SHALL automatically create and migrate the SQLite database located at `/data/stridesync.db` during container startup via `rootfs/etc/cont-init.d/01-db-migrate.sh` using idempotent DDL statements in `app/db/schema.sql`.

#### Scenario: First run on clean volume
- **WHEN** the container starts with an empty `/data` directory
- **THEN** `/data/stridesync.db` is created with all tables, indexes, and constraints.

#### Scenario: Startup with existing database
- **WHEN** the container restarts with an existing database from previous runs
- **THEN** existing tables and records are preserved and any missing tables or columns are created without data loss.

### Requirement: Activity Records Storage
The system SHALL store normalized activity summaries and high-resolution time series in relational tables linked by `activity_id`.

#### Scenario: Storing completed activity summary
- **WHEN** an activity is synced from Garmin Connect
- **THEN** a row is upserted into `activities` capturing duration, distance, pace, HR, cadence, elevation, calories, aerobic/anaerobic training effects, and training load.

#### Scenario: Storing lap splits
- **WHEN** an activity has split or lap records
- **THEN** rows are inserted into `activity_metrics` indexed by `(activity_id, lap_index)` recording per-lap pace, cadence, and heart rate.

#### Scenario: Storing heart rate zone breakdowns
- **WHEN** Garmin returns zone distribution for an activity
- **THEN** rows are stored in `activity_hr_zones` indexed by `(activity_id, zone_number)` recording seconds spent in zones 1 through 5.

#### Scenario: Storing high-resolution samples
- **WHEN** fine-grained track points are available
- **THEN** sample points are recorded in `activity_samples` capturing elapsed time, HR, speed, pace, cadence, elevation, coordinates, and ambient temperature.

### Requirement: Daily Wellness and Recovery Storage
The system SHALL store daily health and recovery indicators in `daily_wellness` and `vo2max_history` keyed by calendar date.

#### Scenario: Storing daily wellness signals
- **WHEN** sleep, HRV, training readiness, and stress metrics are fetched for a date
- **THEN** `daily_wellness` is upserted for that `calendar_date` with sleep scores, sleep stages, HRV status, training readiness score, acute/chronic training load, and stress indicators.

#### Scenario: Graceful handling of missing sensor metrics
- **WHEN** a user device does not report specific metrics (e.g. resting HR or respiration)
- **THEN** the corresponding columns in `daily_wellness` remain `NULL` without aborting the record upsert.

### Requirement: Physiological Baseline Reference Storage
The system SHALL maintain a single-row reference state in `training_baseline` representing current lactate threshold and race predictions.

#### Scenario: Updating training baseline
- **WHEN** fresh physiological baselines are retrieved from Garmin Connect
- **THEN** the row with `id = 1` in `training_baseline` is replaced with the latest lactate threshold HR/pace and 5K/10K/Half/Marathon race predictions.

### Requirement: Equipment and Gear Storage
The system SHALL track gear items and cumulative usage in the `gear` table keyed by Garmin's unique `gear_uuid`.

#### Scenario: Upserting tracked gear
- **WHEN** gear inventory is retrieved
- **THEN** each item is upserted with display name, gear type, status, and total accumulated distance and activities.
