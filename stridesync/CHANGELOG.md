# Changelog

## [Unreleased]

### Added
- **MCP server icon** (milestone Stage 33): the server now declares its own icon (via MCP's
  `Implementation.icons` field, embedded as a base64 `data:` URI from the add-on's existing
  `icon.png`), so MCP clients that render a connector icon — like Claude's mobile app — show
  StrideSync's own icon instead of a generic fallback.

### Fixed
- **Dockerfile never actually shipped `icon.png` inside the container image** — only `app/` and
  `rootfs/` were copied in, so any code reading `icon.png` at runtime (the new server-icon feature
  above) would have silently found nothing on a real install despite working in local
  dev/tests. Added `COPY icon.png ./icon.png`.

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
