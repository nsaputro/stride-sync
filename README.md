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

🚧 Foundational scaffolding — no functional release yet. See milestones in
[`PROJECT_PLAN.md`](PROJECT_PLAN.md).

## Installation (once published)

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add: `https://github.com/nsaputro/stride-sync`
3. Find **StrideSync** → Install → configure your Garmin Connect credentials → Start

## License

[MIT](LICENSE)
