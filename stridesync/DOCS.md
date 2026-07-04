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

## Accounts with MFA/2FA enabled

StrideSync runs headless, so a scheduled sync can't answer an interactive MFA prompt — but MFA
accounts are supported via a **one-time interactive login**, in either of two ways:

### Option A: the add-on's web UI (no terminal needed)

Open the **StrideSync** panel in the Home Assistant sidebar (added by this add-on's ingress
page) and click **Log in to Garmin Connect**. If your account needs an MFA code, you'll be
prompted for it right there.

### Option B: terminal / `docker exec`

If sync fails with `Garmin Connect requires a multi-factor authentication (MFA) code for this
account...`, run:

```bash
docker exec -it <container> python3 -m app.sync.bootstrap_login
```

(on a real HA install, use the **Terminal & SSH** add-on: `ha addons exec <slug> python3 -m
app.sync.bootstrap_login`). Enter the MFA code Garmin sends you when prompted.

Either way, the resulting session is saved to `/data/.garmin_tokens` — every scheduled sync
afterward reuses and refreshes that session without requiring MFA again, until the underlying
session is itself revoked or expires, at which point log in again (either option above).

## Data

Activity data is stored in `/data/stridesync.db` (SQLite). This file persists across add-on
restarts and updates.
