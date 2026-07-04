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

`v0.1.0` is tagged and published to GHCR, but **fails to start** (`ModuleNotFoundError: No
module named 'app'` — see `CHANGELOG.md`) — a fix is in progress. A **pre-release/dev channel**
now exists (`stridesync-dev/`, see Installation below) precisely so a fix like this one can be
verified on a real HA instance before being promoted to a stable release.

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

## Installation (once released)

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
