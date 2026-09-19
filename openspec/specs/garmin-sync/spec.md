## Purpose

Synchronizes running activities, physiological baselines, recovery and wellness signals, training plans, and equipment data from Garmin Connect to local storage.

## Requirements

### Requirement: Garmin Authentication and Session Management
The sync subsystem SHALL authenticate against Garmin Connect using `python-garminconnect` with multi-strategy cascading fallback, support MFA verification, and persist session tokens in the persistent `/data` volume to prevent repeated logins.

#### Scenario: Initial authentication with valid credentials
- **WHEN** Garmin credentials are provided and no valid session token exists
- **THEN** the client authenticates against Garmin Connect and saves the session state to `/data/.garmin_session`.

#### Scenario: Multi-factor authentication challenge
- **WHEN** Garmin Connect requests MFA/2FA during login
- **THEN** the system pauses for user MFA input via web UI or CLI bootstrap without failing the background sync daemon.

#### Scenario: Session token resumption
- **WHEN** a background sync triggers and a valid session token exists in `/data/.garmin_session`
- **THEN** the client resumes the authenticated session without performing a full credentials login.

### Requirement: Scheduled Sync Execution
The sync scheduler SHALL run as an independent supervised s6 daemon (`sync-scheduler`) that polls Garmin Connect at a user-configured interval (default 6 hours).

#### Scenario: Periodic sync trigger
- **WHEN** the configured interval timer elapses
- **THEN** the scheduler initiates an incremental sync cycle for activities, wellness, baselines, and gear.

#### Scenario: Sync failure resilience
- **WHEN** an error occurs during a scheduled sync cycle (network error, API change, or rate limit)
- **THEN** the scheduler logs the error, updates `sync_log` with status `failed`, and continues running for the next interval without terminating the MCP server.

### Requirement: Incremental Activity Syncing
The sync subsystem SHALL query for activities newer than the most recently synced activity in the local database to minimize API calls.

#### Scenario: New activities available
- **WHEN** activities have been logged in Garmin Connect since the last recorded `start_time_local`
- **THEN** the system fetches only the newer activities along with their splits, HR zones, and samples, and inserts them into the database.

#### Scenario: No new activities available
- **WHEN** no activities have been logged since the last sync
- **THEN** the system updates the wellness and baseline metrics without re-querying existing activities.

### Requirement: Historical Data Backfill
The sync subsystem SHALL support one-off historical backfills from a specified start date to populate historical running history.

#### Scenario: User requests backfill from custom start date
- **WHEN** a backfill is triggered from the Settings tab with a specified start date
- **THEN** the system fetches historical activities page by page, streaming live progress updates until the backfill range is complete.

### Requirement: On-Demand Sync
The system SHALL support on-demand immediate sync execution both via CLI flag and via the MCP protocol.

#### Scenario: CLI one-shot sync
- **WHEN** `python3 -m app.sync.scheduler --once` is executed in the container
- **THEN** a single complete sync cycle runs to completion and logs its result before exiting.

#### Scenario: MCP sync_now invocation
- **WHEN** an MCP client calls `sync_now`
- **THEN** the sync cycle executes immediately, blocks until completion, and returns the sync status summary.

### Requirement: Sync Logging and Telemetry
The sync subsystem SHALL record the outcome, timing, and record counts of every sync run in the `sync_log` table.

#### Scenario: Successful sync completion
- **WHEN** all sync tasks finish without uncaught exceptions
- **THEN** a row is inserted in `sync_log` with status `success`, finish timestamp, and count of synced activities.

#### Scenario: Failed sync execution
- **WHEN** a sync run encounters an authentication or network error
- **THEN** a row is inserted in `sync_log` with status `failed` and the error message description.
