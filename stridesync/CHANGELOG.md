# Changelog

## [0.8.1] - 2026-08-11

### Fixed
- **MCP client still showed a generic fallback connector icon after 0.8.0** (milestone Stage 35,
  follow-up to Stage 33): declaring the server's icon via MCP's `Implementation.icons` field
  turned out not to be what a real client actually used to render a connector icon — a live
  add-on log line (`GET /favicon.ico HTTP/1.1 404 Not Found`) caught the client fetching this
  classic browser convention directly instead. New `/favicon.ico` route serves the same
  `icon.png` as `image/png`, not gated by `mcp_auth_token` (same reasoning as `/health` — a
  client fetching a favicon typically hasn't authenticated yet).

[0.8.1]: https://github.com/nsaputro/stride-sync/releases/tag/v0.8.1
