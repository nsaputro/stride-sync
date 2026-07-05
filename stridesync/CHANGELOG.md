# Changelog

## [0.2.2] - 2026-07-05

### Added
- **Temperature in per-activity time-series samples** (`activity_samples` table / the
  `activity_samples` MCP tool): Garmin's per-second chart data includes ambient temperature for
  devices that record it (`directTemperature`), alongside the existing pace/HR/cadence/elevation
  fields — previously fetched but discarded. New `temperature_celsius` column, nullable like
  every other sample field for devices/activities that don't report it. Existing databases get
  the new column via an explicit migration on next startup (`CREATE TABLE IF NOT EXISTS` alone
  doesn't add columns to an already-existing table).

### Changed
- **Rewrote `DOCS.md`'s Claude connection instructions** (milestone v0.9) into two concrete
  setups: Claude Desktop (direct LAN, via `mcp-proxy`) and Claude mobile (via an existing
  Cloudflare Tunnel install). Also documents a real limitation discovered while writing this:
  Claude's "Add custom connector" UI has no field for a static bearer token (OAuth or no-auth
  only), and the MCP server 401's every request when `mcp_auth_token` is set — including
  Claude's own connector, since it can never send one. So `mcp_auth_token` must be left empty for
  the mobile/connector setup to work at all; real protection there comes from a Cloudflare WAF
  rule restricting the tunnel hostname to Anthropic's published MCP-connector egress IP ranges
  instead. Added an "Example prompts" section covering run analysis and racing/target-pace
  questions by training type.

### Fixed
- **"Log in again" silently did nothing for MFA-enabled accounts with an existing session**:
  `Garmin.login()` always prefers resuming a still-valid cached session over a real
  credentials-based login, entirely skipping the MFA challenge, even when the user explicitly
  clicked "Log in again" wanting a genuine re-authentication — reported live by an MFA-enabled
  account that never saw the MFA prompt. `mfa_login.start_login()` gained a `force` parameter
  (passes `tokenstore=None` instead of the real token directory, so `Garmin.login()` has nothing
  to resume from) used whenever a cached session already exists; a failed forced re-login never
  touches the existing session on disk, so scheduled syncs keep working with the old session if
  the new attempt fails.

[0.2.2]: https://github.com/nsaputro/stride-sync/releases/tag/v0.2.2
