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

## Status

All of the add-on's functionality (v0.1–v0.4 in [`PROJECT_PLAN.md`](PROJECT_PLAN.md)) is
implemented: Garmin Connect sync, a continuously-running sync scheduler, an MCP server over
Streamable HTTP, and HA Supervisor add-on packaging. **No version has been tagged/released yet**
— see [`PROJECT_PLAN.md`](PROJECT_PLAN.md) milestone v1.0 for what's left before the first
release.

Until a release is tagged, there are no pre-built images on GHCR — build the add-on standalone
instead (see Quick Start below).

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

docker run --rm -it -p 8765:8765 -v "$(pwd)/.dev-data:/data" stridesync-dev
```

Then point an MCP client at `http://localhost:8765/mcp` — see
[`PROJECT_PLAN.md` §2](PROJECT_PLAN.md#2-mcp-connection) for the Claude Desktop config snippet.

## Installation (once released)

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add: `https://github.com/nsaputro/stride-sync`
3. Find **StrideSync** → Install → configure your Garmin Connect credentials → Start

## Configuration

| Option | Description | Default |
|---|---|---|
| `garmin_username` | Garmin Connect account email | — (required) |
| `garmin_password` | Garmin Connect account password | — (required) |
| `sync_interval_hours` | How often to poll Garmin Connect for new activities | `6` |
| `mcp_port` | Port the MCP server listens on | `8765` |
| `log_level` | Log verbosity (`debug`, `info`, `warning`, `error`) | `info` |

## Known limitation: Garmin auth

StrideSync depends on unofficial, reverse-engineered Garmin Connect libraries. Garmin can change
its login/SSO flow without notice, which can break syncing until the underlying library is
updated. When this happens, StrideSync fails loudly in the add-on log and reports sync staleness
through the MCP server (`last_sync_status` tool) rather than silently serving stale data as if it
were current. See `PROJECT_PLAN.md`'s "Known risk" section for the full design rationale.

## License

[MIT](LICENSE)
