## Purpose

Exposes synced running, wellness, and training data to AI agents via the Model Context Protocol (MCP) over Streamable HTTP with tools for conversational athletic analysis.

## Requirements

### Requirement: Streamable HTTP Transport and Process Isolation
The MCP server SHALL run as an independent supervised s6 service (`mcp-server`) serving Streamable HTTP on a configurable port (default 8765, dev 8766) and SHALL continue serving cached SQLite records if the Garmin sync scheduler fails.

#### Scenario: Normal MCP connection
- **WHEN** an MCP client connects via Streamable HTTP to `http://<host>:<port>/mcp`
- **THEN** the server establishes the MCP session and handles tool discovery and invocation.

#### Scenario: Sync failure isolation
- **WHEN** Garmin sync fails or Garmin credentials are temporarily invalid
- **THEN** the MCP server remains operational and answers queries using the latest successfully synced local data.

### Requirement: Dual-Transport Bearer Authentication
When `mcp_auth_token` is configured, the server SHALL enforce constant-time bearer token validation via both `Authorization: Bearer <token>` headers and URL path segments (`/mcp/<token>`).

#### Scenario: Missing token when auth configured
- **WHEN** `mcp_auth_token` is set and a client requests `/mcp` without providing the token
- **THEN** the server returns HTTP 401 Unauthorized.

#### Scenario: Valid Authorization header
- **WHEN** a client sends `Authorization: Bearer <mcp_auth_token>`
- **THEN** the server validates the token with constant-time comparison and authorizes the session.

#### Scenario: Valid URL path token segment
- **WHEN** a client unable to send custom headers connects to `/mcp/<mcp_auth_token>`
- **THEN** the path middleware translates the path segment into bearer credentials and permits access.

### Requirement: Health and Availability Check
The server SHALL provide an unauthenticated `/health` endpoint returning HTTP 200 with registered tool names when active, and HTTP 503 if tool initialization fails.

#### Scenario: Server healthy
- **WHEN** a GET request is sent to `/health` and tools are registered
- **THEN** the server responds with HTTP 200 and a JSON list of registered tools without requiring authentication.

#### Scenario: Server degraded
- **WHEN** the server has not completed tool initialization
- **THEN** the server responds with HTTP 503 Service Unavailable.

### Requirement: Server Brand Identity and Favicon
The server SHALL declare its icon in MCP server metadata as a base64 PNG data URI and serve the same 128x128 brand icon at `/favicon.ico`.

#### Scenario: MCP handshake icon inspection
- **WHEN** an MCP client inspects the server metadata during initialization
- **THEN** the `Implementation.icons` field contains the StrideSync icon as an image/png data URI.

#### Scenario: Web browser favicon request
- **WHEN** a browser or HTTP client requests `/favicon.ico`
- **THEN** the server returns the PNG binary icon with HTTP 200 and `image/png` content type.

### Requirement: Activity Query MCP Tools
The server SHALL expose read-only tools for inspecting activities, splits, HR zones, and samples: `recent_activities`, `search_activities`, `activity_laps`, `activity_hr_zones`, and `activity_samples`.

#### Scenario: Querying recent runs
- **WHEN** an agent calls `recent_activities` with an optional limit
- **THEN** the server returns the latest running activities sorted chronologically descending.

#### Scenario: Filtering activities by criteria
- **WHEN** an agent calls `search_activities` with date range, activity type, or distance filters
- **THEN** the server returns only matching activities meeting all criteria.

#### Scenario: Retrieving lap splits
- **WHEN** an agent calls `activity_laps` for an `activity_id`
- **THEN** the server returns per-lap duration, distance, pace, cadence, and HR splits.

### Requirement: Physiological Baseline and Trend MCP Tools
The server SHALL expose tools for physiological baselines and longitudinal trends: `training_baseline`, `pace_cadence_hr_trend`, `training_load_summary`, `vo2max_trend`, `resting_hr_trend`, and `daily_wellness`.

#### Scenario: Fetching athlete baseline
- **WHEN** an agent calls `training_baseline`
- **THEN** the server returns lactate threshold HR/pace and race predictions.

#### Scenario: Inspecting daily wellness indicators
- **WHEN** an agent calls `daily_wellness` for a date range
- **THEN** the server returns daily sleep scores, HRV balance, training readiness, and chronic/acute training loads.

### Requirement: On-Demand Sync Control via MCP
The server SHALL expose `last_sync_status` and `sync_now` tools for monitoring and triggering synchronization.

#### Scenario: Checking last sync status
- **WHEN** an agent calls `last_sync_status`
- **THEN** the server returns the timestamp, status ('success' | 'failed' | 'partial'), and record counts of the last sync run.

#### Scenario: Triggering sync now
- **WHEN** an agent calls `sync_now`
- **THEN** the server initiates a sync cycle, blocks until finished, and returns the resulting sync status.
