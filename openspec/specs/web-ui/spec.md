## Purpose

Provides an embedded Home Assistant sidebar Ingress panel and standalone web interface on port 8767 for sync monitoring, weekly mileage visualization, MFA authentication, and backfill controls.

## Requirements

### Requirement: Web UI Serving and Ingress Integration
The web application SHALL be served on port 8767 and SHALL support Home Assistant Ingress header routing (`X-Ingress-Path`) as well as standalone direct browser access.

#### Scenario: Ingress navigation in Home Assistant
- **WHEN** a user navigates to StrideSync from the Home Assistant sidebar
- **THEN** the web UI renders all static assets and API calls relative to the supplied Ingress path without broken links.

#### Scenario: Standalone local access
- **WHEN** a user opens `http://<host>:8767/` directly in a browser
- **THEN** the interface renders fully functional tabs and controls.

### Requirement: Dashboard Tab
The Dashboard tab SHALL display current synchronization health, total synced records by type, an immediate "Sync now" action, and recent activities.

#### Scenario: Viewing dashboard status
- **WHEN** the Dashboard tab is opened
- **THEN** the user sees the last sync status, timestamp, record count badges (activities, wellness, baseline), and a table of the latest activities.

#### Scenario: Triggering sync from dashboard
- **WHEN** the user clicks the "Sync now" button
- **THEN** an immediate sync is initiated and the UI updates the sync status badge upon completion.

### Requirement: Running Analytics Tab
The Running tab SHALL display heart rate zone ranges and aggregate weekly mileage grouped Monday through Sunday with most recent weeks first.

#### Scenario: Viewing weekly volume
- **WHEN** the Running tab is opened
- **THEN** weekly distances are displayed in chronological order (recent first) grouped by calendar week along with heart rate zone thresholds.

### Requirement: Settings, MFA, and Backfill Controls
The Settings tab SHALL provide Garmin account configuration, interactive MFA code submission, historical backfill trigger with live progress streaming, and a diagnostics panel.

#### Scenario: Submitting MFA verification code
- **WHEN** Garmin Connect demands a 2FA code during login
- **THEN** the Settings tab displays an MFA entry modal and submits the user's code to finalize the authentication session.

#### Scenario: Executing historical backfill
- **WHEN** a user specifies a start date and clicks "Start Backfill"
- **THEN** the system fetches historical data page by page and updates a live progress bar until finished.

#### Scenario: Inspecting diagnostic logs
- **WHEN** a user views the Diagnostics panel in Settings
- **THEN** recent sync logs, error messages, and database stats are displayed for troubleshooting.
