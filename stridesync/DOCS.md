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

## Connecting Claude to StrideSync

StrideSync's MCP server speaks Streamable HTTP at:

```
http://homeassistant.local:8765/mcp
```

(replace `homeassistant.local` with your HA server's hostname/IP, and `8765` with `mcp_port` if
you changed it). How you connect a Claude client to that URL differs depending on whether the
client is on your LAN or reaching it remotely — see the two setups below.

### Claude Desktop — direct connection (same network as Home Assistant)

Claude Desktop's built-in MCP config (`claude_desktop_config.json`) launches local processes over
stdio, so reaching a remote Streamable HTTP server goes through `mcp-proxy` running as a local
stdio↔HTTP bridge on your own machine:

1. Install `mcp-proxy`: `pipx install mcp-proxy` or `uv tool install mcp-proxy`.
2. Add this to `claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "stridesync": {
         "command": "mcp-proxy",
         "args": ["http://homeassistant.local:8765/mcp"]
       }
     }
   }
   ```
3. If you've set `mcp_auth_token`, add it as a header instead — `mcp-proxy` is a local process, so
   it can send custom headers freely:
   ```json
   "args": [
     "--headers", "Authorization", "Bearer <mcp_auth_token>",
     "http://homeassistant.local:8765/mcp"
   ]
   ```
4. Restart Claude Desktop — StrideSync's tools should appear in a new conversation.

This only works while your computer can reach `homeassistant.local` directly (same LAN, or a
VPN into it) — `mcp-proxy` runs on your machine, so it resolves that hostname the same way any
other device on your network does.

### Claude mobile (or Desktop away from home) — via Cloudflare Tunnel

Claude's mobile app, and the "Add custom connector" feature in Desktop/claude.ai settings, don't
run a local process — they connect to your remote MCP server directly from Anthropic's cloud
infrastructure, so the server needs a **public** URL. This is a different connection path from
the LAN setup above, with an important limitation to know about first:

> **Known limitation**: Claude's custom-connector UI currently only supports OAuth or no
> authentication — there's no field for a static bearer token, so it **cannot** send
> StrideSync's `mcp_auth_token` header. Setting `mcp_auth_token` still blocks any *other* client
> from connecting without it, but it does nothing to protect the tunnel hostname against Claude's
> own official connector traffic, which arrives with no auth header at all. Real protection for
> this path comes from restricting *who can reach the tunnel hostname in the first place*, not
> from `mcp_auth_token`.

Setup:

1. **Set `mcp_auth_token`** anyway (e.g. `openssl rand -hex 32`) — defense-in-depth against any
   other client, and free if Claude adds custom-header support to connectors later.
2. **Point your Cloudflare Tunnel at the MCP port**, not the ingress port: add a public hostname
   in your tunnel config routing to `http://homeassistant.local:8765` (`8765` = `mcp_port`). Don't
   route the tunnel at `8767` (ingress) — that's the browser-only MFA login page, not the MCP
   protocol.
3. **Add a Cloudflare WAF rule restricting that hostname to Anthropic's published MCP-connector
   egress ranges** (Cloudflare dashboard → Security → WAF → Custom rules): block or challenge all
   traffic to the tunnel hostname *except* from Anthropic's current ranges (at the time of
   writing, `160.79.104.0/21` for IPv4 and `2607:6bc0::/48` for IPv6 — double-check these against
   [Anthropic's published IP-address reference](https://platform.claude.com/docs/en/api/ip-addresses)
   before relying on them, since ranges can change). This is real access control: a request from
   outside those ranges never reaches StrideSync at all, regardless of any header.
4. In Claude, go to **Settings → Connectors → Add custom connector** and enter:
   - URL: `https://<your-tunnel-hostname>/mcp`
   - Leave Advanced settings (OAuth Client ID/Secret) blank — StrideSync doesn't implement OAuth.

Custom-connector configuration is account-level in Claude, so once added it's available on any
device signed into that account, including mobile.

## Example prompts

Once connected, just ask Claude — no dashboard needed. A few starting points:

**Reviewing a recent run**
- "What was my last run like? Break down the pace, cadence, and heart-rate zones."
- "Compare my last 3 long runs — is my pace at the same heart rate improving?"
- "Look at the mile splits for my run yesterday — did I go out too fast?"

**Trends over time**
- "How has my easy-run pace at a given heart rate changed over the last 3 months?"
- "Summarize my training load over the last 30 days — am I ramping up too quickly?"
- "Is there any sign of overtraining in my recent heart-rate trends?"

**Racing pace / target paces by training type**

These lean on your training baseline (current lactate threshold pace/HR and Garmin's race-time
predictions) plus your recent activity trend — not every Garmin device/account has this data, so
make sure at least one sync has run first:

- "Based on my current lactate threshold pace, what should my target pace be for an easy run vs.
  a long run vs. a threshold run?"
- "I'm training for a half marathon — using my recent pace and HR trends, what race pace is
  realistic right now?"
- "What heart-rate zone should I target for recovery runs, and how does that compare to what I
  actually ran this week?"
- "Build a target-pace table for my next training block: easy, long run, marathon pace,
  threshold, and interval pace, based on my current fitness."
- "My 10K race is in 6 weeks — what training paces should I be running now, and how should they
  change as race day gets closer?"

**Sync health**
- "Has my Garmin sync run recently, or is my data stale?"

Claude answers these by calling StrideSync's MCP tools directly (recent activities, lap splits,
pace/cadence/HR trend, training load, training baseline, HR zones, per-activity samples,
last-sync status) — no need to open Garmin Connect or the StrideSync web UI yourself.

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
