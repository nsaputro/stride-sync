# Changelog

## [Unreleased]

### Added
- **Path-embedded `mcp_auth_token`: `/mcp/<token>`** (milestone Stage 36): the shared secret can
  now be supplied as part of the URL (`https://<host>/mcp/<mcp_auth_token>`) instead of only via
  an `Authorization: Bearer` header — closing a documented gap where Claude's cloud/mobile
  custom-connector UI, which has no field for a custom header, could only be used with
  `mcp_auth_token` left unset entirely. `DOCS.md`'s Claude-mobile/Cloudflare-Tunnel setup
  instructions updated accordingly; the empty-token + WAF-only path remains supported for anyone
  who'd rather not put a secret in a URL.

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
