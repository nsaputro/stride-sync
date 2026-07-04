"""MCP server entry point — python3 -m app.mcp.server

Serves synced Garmin activity data to MCP clients over Streamable HTTP. Runs as the mcp-server
s6 service (rootfs/etc/services.d/mcp-server/run), independent of sync-scheduler — a broken
Garmin sync degrades data freshness only; this server keeps answering from whatever was last
synced (see PROJECT_PLAN.md §1, "Isolate the blast radius").

Built directly on `fastmcp` rather than wrapped with `mcp-proxy`: modern `fastmcp` (the dependency
`garmy-mcp` itself is built on) serves Streamable HTTP natively via
`mcp.run(transport="http", ...)`, so no separate stdio→HTTP bridge process is needed inside the
container. `mcp-proxy` is still used client-side for stdio-only clients like Claude Desktop — see
PROJECT_PLAN.md §2 — that is a different process, on a different machine.

`garmy-mcp`'s own bundled MCP server (`garmy.mcp.server.create_mcp_server`) was considered instead
of a custom one, but its schema-specific tool (`get_health_summary`) queries a `daily_health_metrics`
table that doesn't exist in our schema (see `app/db/schema.sql`), and PROJECT_PLAN.md's milestone
v0.3 calls for purpose-built tools (recent activities, pace/cadence/HR trend, training load
summary, last-sync status) rather than a generic SQL-query tool — exactly the "or an equivalent
MCP tool/resource layer built directly on the SQLite schema" fallback the architecture section
already anticipated.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from app.config import Settings

logger = logging.getLogger(__name__)

_MIN_LIMIT = 1
_MAX_LIMIT = 200
_MIN_DAYS = 1
_MAX_DAYS = 365


def _connect_readonly(db_path: str) -> sqlite3.Connection:
    """Open a read-only connection — the MCP server must never write to the sync scheduler's DB."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def list_recent_activities(conn: sqlite3.Connection, limit: int = 20) -> List[Dict[str, Any]]:
    """Most recent activities, newest first, with distance/pace/cadence/HR/training load."""
    limit = _clamp(limit, _MIN_LIMIT, _MAX_LIMIT)
    rows = conn.execute(
        """
        SELECT activity_id, activity_name, activity_type, start_time_local, duration_seconds,
               distance_meters, average_pace_sec_per_km, average_hr, max_hr,
               average_cadence_spm, max_cadence_spm, elevation_gain_meters, calories,
               aerobic_training_effect, anaerobic_training_effect, training_effect_label,
               activity_training_load
        FROM activities
        ORDER BY start_time_local DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_activity_laps(conn: sqlite3.Connection, activity_id: int) -> List[Dict[str, Any]]:
    """Per-lap splits for one activity — how pace/cadence/HR varied over its course."""
    rows = conn.execute(
        """
        SELECT lap_index, start_time_gmt, duration_seconds, distance_meters,
               average_speed_mps, pace_sec_per_km, average_hr, max_hr, average_cadence_spm,
               max_cadence_spm
        FROM activity_metrics
        WHERE activity_id = ?
        ORDER BY lap_index
        """,
        (activity_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_pace_cadence_hr_trend(conn: sqlite3.Connection, days: int = 30) -> List[Dict[str, Any]]:
    """Per-activity pace/cadence/HR over the last N days, oldest first — for spotting trends.

    Filters on `start_time_local`, which is stored without a timezone offset; the `days` window
    is therefore approximate by a few hours, not exact to the second — acceptable for a trend
    query, not for anything that needs to-the-second precision.
    """
    days = _clamp(days, _MIN_DAYS, _MAX_DAYS)
    rows = conn.execute(
        """
        SELECT start_time_local, activity_name, activity_type, distance_meters,
               average_pace_sec_per_km, average_cadence_spm, average_hr
        FROM activities
        WHERE start_time_local >= datetime('now', '-' || ? || ' days')
        ORDER BY start_time_local ASC
        """,
        (days,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_training_load_summary(conn: sqlite3.Connection, days: int = 30) -> Dict[str, Any]:
    """Aggregate training load / training effect over the last N days."""
    days = _clamp(days, _MIN_DAYS, _MAX_DAYS)
    row = conn.execute(
        """
        SELECT COUNT(*) AS activity_count,
               ROUND(SUM(activity_training_load), 1) AS total_training_load,
               ROUND(AVG(activity_training_load), 1) AS avg_training_load,
               ROUND(AVG(aerobic_training_effect), 2) AS avg_aerobic_training_effect,
               ROUND(AVG(anaerobic_training_effect), 2) AS avg_anaerobic_training_effect
        FROM activities
        WHERE start_time_local >= datetime('now', '-' || ? || ' days')
        """,
        (days,),
    ).fetchone()
    result = dict(row)
    result["period_days"] = days
    return result


def get_last_sync_status(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Outcome of the most recent sync attempt, so staleness is never silent (see CLAUDE.md)."""
    row = conn.execute(
        """
        SELECT started_at, finished_at, status, activities_synced, error_message
        FROM sync_log
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return {"status": "never_synced"}
    return dict(row)


def create_server(settings: Settings) -> FastMCP:
    """Build the FastMCP server, wiring each tool to a fresh read-only connection per call."""
    mcp: FastMCP = FastMCP("StrideSync")

    @mcp.tool()
    def recent_activities(limit: int = 20) -> List[Dict[str, Any]]:
        """List the most recent Garmin activities, newest first.

        Args:
            limit: Maximum number of activities to return (1-200, default 20).
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return list_recent_activities(conn, limit)
        finally:
            conn.close()

    @mcp.tool()
    def activity_laps(activity_id: int) -> List[Dict[str, Any]]:
        """Get per-lap splits for one activity, showing how pace/cadence/HR varied over it.

        Args:
            activity_id: The activity's id, from `recent_activities`.
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return get_activity_laps(conn, activity_id)
        finally:
            conn.close()

    @mcp.tool()
    def pace_cadence_hr_trend(days: int = 30) -> List[Dict[str, Any]]:
        """Get pace/cadence/HR for every activity in the last N days, oldest first — use this to
        spot trends (e.g. is pace improving, is cadence drifting) rather than a single snapshot.

        Args:
            days: How many days back to look (1-365, default 30).
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return get_pace_cadence_hr_trend(conn, days)
        finally:
            conn.close()

    @mcp.tool()
    def training_load_summary(days: int = 30) -> Dict[str, Any]:
        """Get aggregate training load and training effect over the last N days.

        Args:
            days: How many days back to summarize (1-365, default 30).
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return get_training_load_summary(conn, days)
        finally:
            conn.close()

    @mcp.tool()
    def last_sync_status() -> Dict[str, Any]:
        """Get the outcome of the most recent Garmin sync attempt (status, timing, error if any).

        Always check this before answering questions about recent activities — if the last sync
        failed or is stale, say so rather than treating the data as current.
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return get_last_sync_status(conn)
        finally:
            conn.close()

    return mcp


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(level=settings.log_level.upper())

    logger.info("Starting StrideSync MCP server on port %d (path /mcp)", settings.mcp_port)
    mcp = create_server(settings)
    # show_banner=False also skips fastmcp's PyPI update-check network call (see
    # fastmcp.utilities.cli.log_server_banner) — an add-on service shouldn't phone home on
    # startup, and the ANSI-art banner doesn't render usefully in the HA add-on log viewer.
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=settings.mcp_port,
        path="/mcp",
        show_banner=False,
    )


if __name__ == "__main__":
    main()
