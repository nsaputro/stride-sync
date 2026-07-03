# StrideSync

Syncs your Garmin Connect running activities into a local database and exposes them to Claude (or
any MCP client) over the network — cadence, pace, heart-rate trends, training load — without
opening a dashboard.

**Read-only.** StrideSync never writes back to Garmin Connect.

## Installation

1. Settings → Add-ons → Add-on Store → ⋮ → Repositories
2. Add: `https://github.com/nsaputro/stride-sync`
3. Find **StrideSync** → Install

## Configuration

| Option | Description | Default |
|---|---|---|
| `garmin_username` | Garmin Connect account email | — (required) |
| `garmin_password` | Garmin Connect account password | — (required) |
| `sync_interval_hours` | How often to poll Garmin Connect for new activities | `6` |
| `mcp_port` | Port the MCP server listens on | `8765` |
| `log_level` | Log verbosity (`debug`, `info`, `warning`, `error`) | `info` |

## Connecting an MCP client

Point your MCP client at:

```
http://homeassistant.local:8765/mcp
```

For Claude Desktop, see the config snippet in
[`PROJECT_PLAN.md`](https://github.com/nsaputro/stride-sync/blob/main/PROJECT_PLAN.md#2-mcp-connection).

## Known limitation: Garmin auth

StrideSync depends on unofficial, reverse-engineered Garmin Connect libraries. Garmin can change
its login/SSO flow without notice (this happened in March 2026), which can break syncing until
the underlying library is updated. When this happens, StrideSync fails loudly in the add-on log
and reports sync staleness through the MCP server rather than silently serving stale data as if
it were current.

## Data

Activity data is stored in `/data/stridesync.db` (SQLite). This file persists across add-on
restarts and updates.
