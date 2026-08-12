# Changelog

## [0.9.0] - 2026-08-12

### Added
- **Path-embedded `mcp_auth_token`: `/mcp/<token>`** (milestone Stage 36): the shared secret can
  now be supplied as part of the URL (`https://<host>/mcp/<mcp_auth_token>`) instead of only via
  an `Authorization: Bearer` header — closing a documented gap where Claude's cloud/mobile
  custom-connector UI, which has no field for a custom header, could only be used with
  `mcp_auth_token` left unset entirely. `stridesync/DOCS.md`'s Claude-mobile/Cloudflare-Tunnel
  setup instructions updated accordingly; the empty-token + WAF-only path remains supported for
  anyone who'd rather not put a secret in a URL.

[0.9.0]: https://github.com/nsaputro/stride-sync/releases/tag/v0.9.0
