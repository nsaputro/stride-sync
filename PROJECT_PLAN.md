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

- Wraps [`garmy-mcp`](https://pypi.org/project/garmy-mcp/) (or an equivalent MCP tool/resource
  layer built directly on the SQLite schema, if `garmy-mcp`'s data model doesn't line up with
  what the sync service stores) with [`mcp-proxy`](https://github.com/sparfenyuk/mcp-proxy).
- Exposes **Streamable HTTP transport**, not stdio — this add-on runs on the Home Assistant
  server, not on the same machine as the Claude client, so an stdio-piped subprocess isn't an
  option. `mcp-proxy` bridges the stdio-based MCP server implementation to an HTTP endpoint
  clients can reach over the network.
- Runs as its own **s6 service** (`rootfs/etc/services.d/mcp-server/run`) on a **configurable
  port** (default `8765`).
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

### v0.1 — Manual sync, verify schema ⬜

- ⬜ `app/sync/garmin_client.py`: authenticate against Garmin Connect via `garmy`
- ⬜ SQLite schema defined and created on first run (`activities`, `activity_metrics` /
  time-series table for HR & pace, `sync_log`)
- ⬜ Manual sync runnable via CLI inside the container (`python3 -m app.sync.scheduler --once`)
  for verifying auth + schema without waiting on the scheduler
- ⬜ Inspect the resulting SQLite DB by hand to confirm the schema captures cadence, pace, HR,
  and training load fields Garmin actually returns

### v0.2 — Scheduled sync service ⬜

- ⬜ `rootfs/etc/services.d/sync-scheduler/run` — s6 service wrapping the scheduler loop
- ⬜ `sync_interval_hours` read from `/data/options.json` via `bashio::config`, default `6`
- ⬜ Sync runs continuously without manual invocation; verified across a container restart
  (interval timer state doesn't need to persist — just re-arms on start)
- ⬜ `sync_log` populated on every run (success and failure paths)
- ⬜ Graceful failure path exercised: simulate a broken Garmin auth flow and confirm it logs
  clearly and doesn't crash the service loop

### v0.3 — MCP server over HTTP ⬜

- ⬜ `app/mcp/server.py` — `garmy-mcp` (or equivalent) wired to the sync scheduler's SQLite DB
- ⬜ `mcp-proxy` wrapping the server, exposing Streamable HTTP on `mcp_port` (default `8765`)
- ⬜ `rootfs/etc/services.d/mcp-server/run` — s6 service for the MCP server, independent of
  `sync-scheduler`
- ⬜ Tested end-to-end with Claude Desktop using the config snippet in §2, against a container
  run standalone (not yet installed into HA)
- ⬜ MCP tools cover: recent activities, pace/cadence/HR trend over a date range, training load
  summary, and last-sync status

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
