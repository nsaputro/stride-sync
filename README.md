# 🏃 StrideSync

A Home Assistant add-on that syncs Garmin Connect running data and exposes it to Claude via MCP
for conversational analysis — cadence, pace, heart-rate trends, training load.

Runs continuously on your Home Assistant server. No local-only setup, no client-side install
step — connect any MCP client (e.g. Claude Desktop) to it over the network.

**Read-only**: StrideSync never writes back to Garmin Connect.

See [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for architecture details, MCP connection instructions,
and milestones. See [`CLAUDE.md`](CLAUDE.md) for repository conventions and local development
setup.

---

## Features

- **Automatic syncing** — polls Garmin Connect on a configurable interval (default every 6h) and
  writes activities, laps, HR-zone breakdowns, per-activity sample series, and training-load
  data to a local SQLite database in the add-on's `/data` volume.
- **MCP server** (Streamable HTTP, port `8765`) exposing 8 tools to any MCP client — recent
  activities, per-lap splits, pace/cadence/HR trend over N days, aggregate training load,
  training baseline (lactate threshold, race predictions), per-activity HR zones, per-activity
  time-series samples (pace/HR/cadence/elevation/temperature), and last-sync status.
- **Web UI** (Home Assistant sidebar panel, or standalone on port `8767`) with three tabs:
  - **Dashboard** — login status, total activities synced, last-sync outcome, and your most
    recent activities.
  - **Running** — total distance per calendar week (Monday–Sunday), most recent week first.
  - **Settings** — one-off backfill from any start date (regular syncs only fetch your most
    recent activities), with a live progress bar for wide date ranges.
- **One-time MFA/2FA login** via the web UI or a CLI bootstrap command — no re-entry needed on
  every scheduled sync afterward.
- **Optional bearer-token auth** (`mcp_auth_token`) for the MCP server, so it's safe to expose
  beyond your LAN (e.g. through a Cloudflare Tunnel) without leaking personal health data.

## Why run this as a Home Assistant add-on?

StrideSync could be a standalone Docker container on any machine — running it as an HA add-on
instead means it piggybacks on infrastructure most HA users already have set up for their smart
home, rather than standing up a new always-on service from scratch:

- **Already-on, already-monitored host.** Home Assistant runs 24/7 as your automation hub — no
  separate VPS, NAS, or Raspberry Pi to provision, patch, and keep awake just to sync running
  data.
- **Remote access without new infrastructure.** If you already use the official **Home Assistant
  Android/iOS app** with Nabu Casa remote access (or your own reverse proxy) to reach your HA
  instance away from home, the StrideSync ingress panel (Dashboard/Running/Settings) rides along
  for free — no separate mobile app, port, or login to set up.
- **Reuses your existing tunnel for MCP.** Many HA users already run the **Cloudflare Tunnel**
  add-on (or a similar reverse-proxy add-on) to reach their instance remotely. Pointing that same
  tunnel at StrideSync's MCP port is how Claude on mobile reaches your Garmin data — no new
  domain, certificate, or hosting to manage (see `stridesync/DOCS.md` for how to secure that
  path, since Claude's mobile connector can't send `mcp_auth_token`).
- **Backed up for free.** Home Assistant's built-in **Settings → System → Backups** includes
  every add-on's `/data` by default, so your synced Garmin history is covered by whatever backup
  schedule you already have for the rest of your HA config — nothing extra to configure or
  remember.
- **One set of credentials and updates to maintain.** Garmin credentials and the MCP auth token
  live in the same options UI as every other add-on, and updates arrive through the Add-on Store
  like any other add-on — not a separate `docker pull` / systemd unit to babysit.

## Quick Start

You do not need a Home Assistant instance to try StrideSync — build and run it standalone first
(see `CLAUDE.md`'s Local Development & Testing section for the full walkthrough):

```bash
docker build -t stridesync-dev ./stridesync

mkdir -p .dev-data
cat > .dev-data/options.json <<'EOF'
{
  "garmin_username": "you@example.com",
  "garmin_password": "changeme",
  "sync_interval_hours": 6,
  "mcp_port": 8765,
  "log_level": "info"
}
EOF

docker run --rm -it -p 8765:8765 -p 8767:8767 -v "$(pwd)/.dev-data:/data" stridesync-dev
```

Then point an MCP client at `http://localhost:8765/mcp` — see
[`PROJECT_PLAN.md` §2](PROJECT_PLAN.md#2-mcp-connection) for the Claude Desktop config snippet.

For an MFA/2FA account, open `http://localhost:8767/` for the one-time login UI (this is what
real HA installs reach through the add-on's ingress panel instead — see the MFA section below).

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add: `https://github.com/nsaputro/stride-sync`
3. Find **StrideSync** → Install → configure your Garmin Connect credentials → Start

## Installation (dev channel)

1. Add the same repository URL — HA will also list **StrideSync (dev)**
2. Install it alongside stable; it defaults to host port `8766` (stable uses `8765`)

## Configuration

| Option | Description | Default |
|---|---|---|
| `garmin_username` | Garmin Connect account email | — (required) |
| `garmin_password` | Garmin Connect account password | — (required) |
| `sync_interval_hours` | How often to poll Garmin Connect for new activities | `6` |
| `mcp_port` | Port the MCP server listens on | `8765` |
| `log_level` | Log verbosity (`debug`, `info`, `warning`, `error`) | `info` |
| `mcp_auth_token` | Bearer token required to reach the MCP server. Leave empty for LAN-only access; set before exposing `mcp_port` beyond your LAN (see `stridesync/DOCS.md`) | `""` (disabled) |

## Example Claude Skill

StrideSync's MCP tools work fine with ad-hoc prompts, but [`docs/skills/running-coach/`](docs/skills/running-coach/SKILL.md)
is an example [Claude Skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) that
turns them into a structured coaching workflow — race target tracking, training-progression
checks, recovery/readiness cross-referencing, and lap-level analysis of structured workouts. See
`docs/skills/README.md` for how to install it. Optional, not required to use StrideSync.

## Known limitation: Garmin auth

StrideSync depends on unofficial, reverse-engineered Garmin Connect libraries. Garmin can change
its login/SSO flow without notice, which can break syncing until the underlying library is
updated. When this happens, StrideSync fails loudly in the add-on log and reports sync staleness
through the MCP server (`last_sync_status` tool) rather than silently serving stale data as if it
were current. See `PROJECT_PLAN.md`'s "Known risk" section for the full design rationale.

**Accounts with MFA/2FA enabled** need a one-time interactive login — either via the add-on's
ingress web UI (StrideSync panel in the HA sidebar → **Log in to Garmin Connect**) or, without a
real HA instance, `docker exec -it <container> python3 -m app.sync.bootstrap_login` (on a real HA
install, `ha addons exec <slug> python3 -m app.sync.bootstrap_login` via the Terminal & SSH
add-on). Enter the code Garmin sends you, and every scheduled sync afterward reuses that session
without needing MFA again. See `DOCS.md` for details.

## License

[MIT](LICENSE)
