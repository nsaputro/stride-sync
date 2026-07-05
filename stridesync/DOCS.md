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
| `mcp_auth_token` | Bearer token required to reach the MCP server. Leave empty for LAN-only access; **set this before exposing `mcp_port` beyond your LAN** (see below). | `""` (disabled) |

## Connecting an MCP client

Point your MCP client at:

```
http://homeassistant.local:8765/mcp
```

For Claude Desktop, see the config snippet in
[`PROJECT_PLAN.md`](https://github.com/nsaputro/stride-sync/blob/main/PROJECT_PLAN.md#2-mcp-connection).

## Web UI

Open the **StrideSync** panel in the Home Assistant sidebar for a small dashboard alongside the
Garmin login flow:

- **Dashboard** — login status, total activities synced, last-sync outcome, and your most recent
  activities (name, date, distance).
- **Running** — total distance per calendar week (Monday–Sunday), most recent week first.
- **Settings** — one-off backfill: pick a start date and StrideSync fetches every activity from
  then through today, in addition to what regular syncs already cover. Regular syncs only fetch
  your most recent activities (`sync_interval_hours`, count-based); backfill is for pulling in
  older history a regular sync would never reach. A wide date range can take a while — each
  activity costs several Garmin API calls, so backfilling years of daily activity could take
  minutes. The backfill runs in the background and the page shows a live progress bar
  ("N / total activities"); it's safe to navigate away and come back — the backfill keeps
  running server-side either way, and reopening the **Settings** tab picks the progress bar back
  up (or shows the result, once it's done).

## Remote access (e.g. Claude on mobile, over a Cloudflare Tunnel)

StrideSync's MCP server is reachable over the network by design (Streamable HTTP, not stdio) —
so it works the same way whether the client is on your LAN or reaching it through a tunnel like
`cloudflared`. Two things needed:

1. **Set `mcp_auth_token`** to a long random string (e.g. `openssl rand -hex 32`) in the add-on's
   configuration. The MCP server has no auth by default — fine when only your LAN can reach
   `mcp_port`, not fine once a public hostname points at it. With this set, every request must
   include `Authorization: Bearer <mcp_auth_token>` or gets rejected with `401`.
2. **Point your Cloudflare Tunnel at the MCP port**, not the ingress port: add a public hostname
   in your tunnel configuration routing to `http://homeassistant.local:8765` (or your HA host's
   address) — `8765` is `mcp_port`, the same port `ports:` maps in `config.yaml`. Do **not** route
   the tunnel at `8767` (the ingress port) — that serves the browser-only MFA login page, not the
   MCP protocol.

Then configure your MCP client (e.g. Claude's custom connector settings) with:
- URL: `https://<your-tunnel-hostname>/mcp`
- Auth: bearer token = the `mcp_auth_token` value you set above

Custom-connector configuration is account-level in Claude, so once added it's available from any
device signed into that account, including mobile.

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
