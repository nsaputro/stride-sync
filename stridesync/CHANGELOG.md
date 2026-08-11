# Changelog

## [Unreleased]

### Fixed
- **MCP client still showed a generic fallback connector icon after 0.8.0** (milestone Stage 35,
  follow-up to Stage 33): declaring the server's icon via MCP's `Implementation.icons` field
  turned out not to be what a real client actually used to render a connector icon — a live
  add-on log line (`GET /favicon.ico HTTP/1.1 404 Not Found`) caught the client fetching this
  classic browser convention directly instead. New `/favicon.ico` route serves the same
  `icon.png` as `image/png`, not gated by `mcp_auth_token` (same reasoning as `/health` — a
  client fetching a favicon typically hasn't authenticated yet).

## [0.8.0] - 2026-08-11

### Added
- **MCP server icon** (milestone Stage 33): the server now declares its own icon (via MCP's
  `Implementation.icons` field, embedded as a base64 `data:` URI from the add-on's existing
  `icon.png`), so MCP clients that render a connector icon — like Claude's mobile app — show
  StrideSync's own icon instead of a generic fallback.

- **`running-coach` example skill: short-burst Sprint session guidance** (milestone Stage 34,
  `docs/skills/running-coach/SKILL.md` follow-up): for Sprint sessions built from very short
  (e.g. 10-15s, depending on the Garmin training plan) max-effort bursts followed by much longer
  (e.g. 3 min) jog recoveries, use a recovery lap's average HR rather than its max HR when judging
  how easy/controlled the jog was — the max is residual carryover from the preceding burst, not
  the jog's own intensity. Purely additive documentation — no application code changed.

### Fixed
- **Dockerfile never actually shipped `icon.png` inside the container image** — only `app/` and
  `rootfs/` were copied in, so any code reading `icon.png` at runtime (the new server-icon feature
  above) would have silently found nothing on a real install despite working in local
  dev/tests. Added `COPY icon.png ./icon.png`.

[0.8.0]: https://github.com/nsaputro/stride-sync/releases/tag/v0.8.0
