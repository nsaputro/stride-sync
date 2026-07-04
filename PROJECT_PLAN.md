# 🏃 StrideSync — Project Plan

**A Home Assistant add-on that syncs Garmin Connect running data and exposes it to Claude via MCP for conversational analysis**

---

## Vision

StrideSync keeps your Garmin Connect running data flowing into a database you own, running
continuously on the same server as the rest of your home automation — no laptop cron job, no
local-only setup, nothing to remember to start. It exposes that data to Claude (or any MCP
client) over the network so you can ask conversational questions about your training — cadence
trends, pace splits, heart-rate zones, training load — without opening a dashboard.

It is **read-only**: StrideSync never writes back to Garmin. It only reads activities and stores
them locally.

---

## 1. Architecture

```
                          ┌─────────────────────────────────────────┐
                          │   HA Add-on container (s6-overlay)        │
                          │                                           │
  Garmin Connect  ◄───────┤  sync-scheduler (s6 service)              │
   (unofficial API)       │    - garmy / python-garminconnect          │
                          │    - runs every N hours (configurable)     │
                          │    - writes to SQLite in /data             │
                          │                                           │
                          │  mcp-server (s6 service)                   │
                          │    - garmy-mcp wrapped with mcp-proxy       │
  Claude Desktop  ◄───────┤    - Streamable HTTP transport, port 8765  │
   (MCP client, remote)   │    - reads from the same SQLite DB          │
                          └─────────────────────────────────────────┘
```

### Garmin Connect sync

- **Primary library**: [`garmy`](https://pypi.org/project/garmy/) for Garmin Connect
  authentication and activity sync.
- **Fallback**: [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect) if
  `garmy` cannot cover a needed endpoint or breaks in a way `garmy` doesn't recover from first.
  Both libraries sit behind the single `app/sync/garmin_client.py` interface (see `CLAUDE.md`) so
  swapping the underlying library is a one-file change, not a rewrite.
- Auth credentials (`garmin_username` / `garmin_password`) come from add-on options, never
  hardcoded or logged.

### Scheduled sync service

- Runs as its own **s6 service** (`rootfs/etc/services.d/sync-scheduler/run`), independent of the
  MCP server process.
- Interval is **configurable via `config.yaml`**, **default every 6 hours**.
- Writes normalized activity data (pace, cadence, HR series, distance, duration, training load
  metrics reported by Garmin) to a **local SQLite database** stored in the add-on's persistent
  `/data` volume (`/data/stridesync.db`), so it survives add-on restarts and updates.
- Each sync run records its own outcome (success / partial / failed, record count, error message)
  in a `sync_log` table — the MCP server can surface "last successful sync" and "last sync error"
  directly in conversation, rather than a user discovering stale data on their own.

### MCP server

- Built with [`fastmcp`](https://gofastmcp.com) directly (`app/mcp/server.py`), exposing five
  purpose-built tools (`recent_activities`, `activity_laps`, `pace_cadence_hr_trend`,
  `training_load_summary`, `last_sync_status`) on top of `app/db/schema.sql`, rather than
  [`garmy-mcp`](https://pypi.org/project/garmy-mcp/)'s bundled server — `garmy-mcp`'s
  schema-specific tool (`get_health_summary`) queries a `daily_health_metrics` table that doesn't
  exist in our schema, and this milestone wants purpose-built tools, not a generic
  run-arbitrary-SQL tool. This is the "equivalent MCP tool/resource layer built directly on the
  SQLite schema" fallback this section originally anticipated.
- Exposes **Streamable HTTP transport**, not stdio — this add-on runs on the Home Assistant
  server, not on the same machine as the Claude client, so an stdio-piped subprocess isn't an
  option. Modern `fastmcp` (the same library `garmy-mcp` itself depends on) serves Streamable
  HTTP **natively** via `mcp.run(transport="http", ...)` — no separate `mcp-proxy` process runs
  *inside* the add-on. (`mcp-proxy` is still used **client-side**, e.g. by Claude Desktop, to
  bridge its local stdio-only integration to this remote HTTP endpoint — see §2. That is a
  different process, on a different machine, doing a different job.)
- Runs as its own **s6 service** (`rootfs/etc/services.d/mcp-server/run`) on a **configurable
  port** (default `8765`), reading the sync scheduler's SQLite DB over a **read-only** connection
  (`sqlite3.connect("file:...?mode=ro", uri=True)`) — the MCP server must never be able to write
  to the sync scheduler's database.
- **Read-only**: exposes tools/resources for querying activities, trends, and summaries. No
  write-back to Garmin is planned initially (see Milestones — a future write-back milestone would
  need explicit user confirmation flows and is out of scope for v1.0).

### HA add-on configuration (`config.yaml` `options:` / `schema:`)

| Option | Purpose | Default |
|---|---|---|
| `garmin_username` | Garmin Connect account email | — (required) |
| `garmin_password` | Garmin Connect account password | — (required, `password` schema type) |
| `sync_interval_hours` | How often the sync scheduler polls Garmin Connect | `6` |
| `mcp_port` | Port the MCP server listens on (Streamable HTTP) | `8765` |
| `log_level` | Log verbosity for both services | `info` |

All of the above are exposed in the HA Supervisor's add-on Configuration UI automatically once
declared in `config.yaml` — no separate UI code needed.

### Known risk: unofficial Garmin auth breakage

Garmin does not offer a public API for personal Connect data — every sync library in this space
(`garmy`, `python-garminconnect`, etc.) depends on reverse-engineered SSO/login flows that Garmin
can and does change without notice. **This already happened once**: in March 2026, Garmin put
Cloudflare in front of their SSO login, breaking unauthenticated scripted logins across the
ecosystem until the libraries adapted.

Design implications:

- **Fail loud, never silent.** A broken auth flow must produce a clear, actionable log line
  (`bashio::log.error`) and an entry in `sync_log` with `status = "failed"` and the underlying
  exception message — not a sync that silently no-ops and leaves the database looking current.
- **Surface staleness through the MCP server itself.** Any MCP tool that returns activity data
  should be able to report "last successful sync: N days ago" so a conversation with Claude
  surfaces the problem instead of Claude reasoning over stale data as if it were current.
- **No auto-retry storms.** If auth is broken, retrying every sync interval against a broken SSO
  flow risks the account being flagged for suspicious activity. Back off and log distinctly from
  "transient network failure" vs. "auth flow structurally broken, needs a library update."
- **Isolate the blast radius.** Because sync and MCP are separate s6 services, a broken Garmin
  auth flow degrades the sync scheduler only — the MCP server keeps serving whatever was last
  successfully synced, with clear staleness info, rather than the whole add-on going down.

---

## 2. MCP Connection

StrideSync's MCP server is **read-only** — no write-back to Garmin Connect is planned for any
milestone below. Point an MCP client at the add-on's Streamable HTTP endpoint:

```
http://homeassistant.local:8765/mcp
```

(replace `homeassistant.local` with your HA server's hostname/IP, and `8765` with `mcp_port` if
you changed it from the default).

### Claude Desktop configuration

Claude Desktop speaks MCP over stdio to locally-launched processes, so connecting to a *remote*
Streamable HTTP server goes through `mcp-proxy` running as a local stdio↔HTTP bridge on your
machine (distinct from the `mcp-proxy` instance running *inside* the add-on, which bridges the
add-on's internal stdio-based MCP server to HTTP for the network hop):

```json
{
  "mcpServers": {
    "stridesync": {
      "command": "mcp-proxy",
      "args": [
        "http://homeassistant.local:8765/mcp"
      ]
    }
  }
}
```

Add this to Claude Desktop's `claude_desktop_config.json`, restart Claude Desktop, and StrideSync's
tools/resources should appear in a new conversation.

---

## 3. Milestones

### v0.1 — Manual sync, verify schema 🔄

- ✅ `app/sync/garmin_client.py`: authenticate against Garmin Connect via `garmy`, wrapped so
  callers only ever see `GarminAuthError`/`GarminAPIError` (never a raw `garmy` or `requests`
  exception — see the module docstring for why transport-level failures needed their own
  handling, not just `garmy`'s own exception types)
- ✅ SQLite schema defined and created on first run (`activities`, `activity_metrics` as a
  per-lap time-series table for HR & pace, `sync_log`) — see `app/db/schema.sql`
- ✅ Manual sync runnable via CLI inside the container (`python3 -m app.sync.scheduler --once`)
  for verifying auth + schema without waiting on the scheduler
- ⬜ Inspect the resulting SQLite DB by hand to confirm the schema captures cadence, pace, HR,
  and training load fields Garmin actually returns — **still open**. `garmy`'s built-in
  activity summary has no distance/pace/cadence fields at all, so `garmin_client.py` merges it
  with the raw `/activity-service/activity/{id}` and `/activity-service/activity/{id}/splits`
  endpoints; the exact field names there (`summaryDTO`, `lapDTOs`, `averageRunningCadence...`)
  are inferred from the wider Garmin Connect tooling ecosystem, not confirmed against a live
  account — this dev environment has no route to `garmin.com` and no test credentials. Run
  `python3 -m app.sync.scheduler --once` against a real account and check
  `sqlite3 /data/stridesync.db` before ticking this off; adjust the field lookups in
  `garmin_client.py` if any come back `NULL` that shouldn't.
- ✅ CI pipeline (`.github/workflows/ci.yml`): yamllint + hadolint + version-ordering check +
  Python syntax check + `pytest` + Docker build smoke test on every push/PR
- ✅ Release pipeline (`.github/workflows/release.yml`): tags `stridesync/NEXT_VERSION`, builds
  and pushes multi-arch (`amd64`/`aarch64`) images to GHCR, creates a GitHub release, and opens
  the `chore/post-release` PR — see `CLAUDE.md`'s CI / Release section. Not yet run for a real
  release (that's v1.0's last checkbox).

### v0.2 — Scheduled sync service 🔄

- ✅ `rootfs/etc/services.d/sync-scheduler/run` — s6 service wrapping the scheduler loop
  (`app/sync/scheduler.py`'s `run_forever`), now exporting `garmin_username`/`garmin_password`/
  `sync_interval_hours`/`log_level` from `bashio::config` as env vars
- ✅ `sync_interval_hours` read from `/data/options.json` via `bashio::config`, default `6`
- 🔄 Sync runs continuously without manual invocation — verified by running
  `python3 -m app.sync.scheduler` directly (env vars set the way the s6 `run` script sets them)
  and confirming repeated sync passes + a clean exit within seconds of `SIGTERM` (not a multi-hour
  hang). **Not yet verified inside the actual Docker/s6 container** — this sandbox has no Docker
  daemon, so a real container restart (`docker restart`) hasn't been exercised.
- ✅ `sync_log` populated on every run (success and failure paths) — covered by
  `tests/test_scheduler.py::TestRunForever`
- ✅ Graceful failure path exercised: a forced Garmin login failure (real SSO call blocked by this
  sandbox's network policy) confirmed the loop logs the failure, writes it to `sync_log`, and
  keeps running rather than crashing the service — both as a unit test
  (`test_auth_failure_does_not_crash_the_loop`) and live via the CLI

### v0.3 — MCP server over HTTP 🔄

- ✅ `app/mcp/server.py` — built directly on `fastmcp`, wired to the sync scheduler's SQLite DB
  over a read-only connection (see Architecture §1 for why `garmy-mcp`'s bundled server wasn't
  reused as-is)
- ✅ Streamable HTTP on `mcp_port` (default `8765`), served natively by `fastmcp`
  (`transport="http"`) — no `mcp-proxy` process runs inside the add-on (see Architecture §1)
- ✅ `rootfs/etc/services.d/mcp-server/run` — s6 service for the MCP server, independent of
  `sync-scheduler`, now exporting `mcp_port`/`log_level` from `bashio::config`
- 🔄 Tested end-to-end **with a real MCP client over real Streamable HTTP** (`fastmcp.Client`
  connecting to a live `python3 -m app.mcp.server` subprocess, listing tools and calling all
  five) — confirmed the full wire protocol works. **Not tested with Claude Desktop itself** — no
  desktop environment in this sandbox to run it; the config snippet in §2 is unverified against
  the real client.
- ✅ MCP tools cover: recent activities (`recent_activities`), pace/cadence/HR trend over a date
  range (`pace_cadence_hr_trend`), training load summary (`training_load_summary`), and
  last-sync status (`last_sync_status`) — plus `activity_laps` for per-lap detail within one
  activity

### v0.4 — HA Supervisor add-on packaging ⬜

- ⬜ `stridesync/config.yaml` finalized: `options` + `schema` for all five settings in §1
- ⬜ `stridesync/build.yaml` multi-arch (`aarch64`, `amd64`) pinned to a specific
  `ghcr.io/hassio-addons/base` tag
- ⬜ `icon.png` (128×128) and `logo.png` (250×100) — real artwork, replacing scaffolding
  placeholders
- ⬜ Ingress evaluated: if a status/config UI panel is added, wire it through HA ingress; if the
  add-on stays API-only (MCP + maybe a health-check page), document why ingress is skipped
- ⬜ `repository.yaml` verified against this add-on repo added as a custom repository in a real
  HA instance (**Settings → Add-ons → Add-on Store → ⋮ → Repositories**)
- ⬜ Full install-from-repository flow tested: add repo → install → configure options → start →
  confirm both s6 services come up healthy in the HA add-on log viewer

### v1.0 — Documented, versioned, changelog-tracked release ⬜

- ⬜ `DOCS.md` complete: install steps, all config options explained, MCP connection
  instructions, known-risk note about Garmin auth breakage
- ⬜ `README.md` complete with install + quick-start
- ⬜ `CHANGELOG.md` (root) and `stridesync/CHANGELOG.md` (add-on-local) populated for every
  milestone above, in Keep a Changelog format
- ⬜ `stridesync/config.yaml` `version` and `stridesync/NEXT_VERSION` following the versioning
  convention in `CLAUDE.md`
- ⬜ First tagged GitHub release, images published to GHCR for `amd64` + `aarch64`

---

## Getting Started (Development)

### Prerequisites

- Python 3.12+
- Docker

### Build & run the add-on standalone

See **Local Development & Testing** in `CLAUDE.md` for the full standalone `docker build` /
`docker run` walkthrough — you do not need a Home Assistant instance until milestone v0.4.

### Manual sync (v0.1+)

```bash
cd stridesync
pip install -r app/requirements.txt
python3 -m app.sync.scheduler --once   # one-shot sync, doesn't wait for the interval
```

### HA Add-on Installation (once published, v0.4+)

1. Settings → Add-ons → Add-on Store → ⋮ → Repositories
2. Add: `https://github.com/nsaputro/stride-sync`
3. Find **StrideSync** → Install → Configure Garmin credentials → Start

---

_Own your training data — talk to it 🏃_
