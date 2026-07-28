# Changelog

## [0.7.0] - 2026-07-28

### Added
- **`/health` endpoint** (milestone Stage 31): plain, unauthenticated `GET /health` alongside the
  `/mcp` protocol endpoint — returns `200` with the sorted list of registered MCP tool names if
  `list_tools()` succeeds and is non-empty, `503` otherwise. Added after a live report that the
  MCP connection "isn't responding" with no corresponding error in the add-on's own logs, so
  there was no way to tell from outside whether the server process itself was healthy. Not gated
  by `mcp_auth_token`, so it works from a browser/`curl`/external monitoring even when a bearer
  token is required for `/mcp`.
- **Heart rate zone ranges on the "Running" tab** (milestone Stage 32): the web UI's `/running`
  route now lists each of Garmin's 5 HR zones with its bpm range (e.g. "Zone 2 · 130–149 bpm"),
  positioned above the existing weekly mileage list, read from the most recently synced activity's
  `activity_hr_zones` data.

[0.7.0]: https://github.com/nsaputro/stride-sync/releases/tag/v0.7.0
