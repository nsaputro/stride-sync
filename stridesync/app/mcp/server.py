# MCP server entry point — python3 -m app.mcp.server
# Runs as the mcp-server s6 service (rootfs/etc/services.d/mcp-server/run).
# Wraps garmy-mcp (or equivalent) with mcp-proxy, exposing Streamable HTTP on mcp_port.
# See PROJECT_PLAN.md §1 (MCP server) and §2 (MCP Connection). Milestone v0.3.
#
# TODO (v0.3): tools for recent activities, pace/cadence/HR trends, training load summary,
# and last-sync status (read from the sync_log table).
