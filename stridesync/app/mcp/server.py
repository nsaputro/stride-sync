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

**Bearer-token auth (milestone v0.6)**: this server has no auth by default, which is fine for a
LAN-only setup where the HA host's own network boundary is the protection. It stops being fine
the moment this port is reached from outside the LAN (e.g. via a Cloudflare Tunnel public
hostname, requested directly to let Claude on mobile reach it) — this endpoint serves personal
Garmin health/activity data, and someone finding the URL shouldn't be able to just read it. If
`mcp_auth_token` is set, every request must carry `Authorization: Bearer <token>` (checked by
`SharedSecretVerifier` below, via `fastmcp`'s standard `TokenVerifier` mechanism) or get a 401 —
confirmed against a real ASGI request/response cycle, not just unit-tested in isolation. Left
optional (empty = disabled) rather than required, so existing LAN-only installs keep working
without being forced to set one.
"""

from __future__ import annotations

import hmac
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier

from app.config import Settings

logger = logging.getLogger(__name__)


class SharedSecretVerifier(TokenVerifier):
    """Single shared-secret bearer token check — this add-on has exactly one owner, so there's
    no per-user scope/expiry complexity to model, just "is this the configured token." Constant-
    time comparison (`hmac.compare_digest`) avoids a timing side-channel a plain `==` would have.
    """

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        if not hmac.compare_digest(token, self._token):
            return None
        return AccessToken(token=token, client_id="stridesync-mcp-client", scopes=[])

_MIN_LIMIT = 1
_MAX_LIMIT = 200
_MIN_DAYS = 1
_MAX_DAYS = 365
_MAX_SAMPLE_POINTS = 500


def _connect_readonly(db_path: str) -> sqlite3.Connection:
    """Open a read-only connection — the MCP server must never write to the sync scheduler's DB."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
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


def get_training_baseline(conn: sqlite3.Connection) -> Dict[str, Any]:
    """The athlete's current lactate threshold HR/pace + Garmin's own race-time predictions —
    see PROJECT_PLAN.md milestone v0.5. This is the reference point for judging whether an
    activity's HR/pace represents an easy, threshold, or hard effort; without it, "average HR
    150" has no meaning. Not every account/device has this data (see
    `GarminClient.fetch_training_baseline`'s docstring) — returns a clear "unavailable" status
    rather than a row of nulls when that's the case.
    """
    row = conn.execute(
        """
        SELECT synced_at, lactate_threshold_hr, lactate_threshold_speed_mps,
               lactate_threshold_pace_sec_per_km, race_prediction_5k_seconds,
               race_prediction_10k_seconds, race_prediction_half_marathon_seconds,
               race_prediction_marathon_seconds
        FROM training_baseline
        WHERE id = 1
        """
    ).fetchone()
    if row is None:
        return {"status": "unavailable"}
    return dict(row)


def get_activity_hr_zones(conn: sqlite3.Connection, activity_id: int) -> List[Dict[str, Any]]:
    """Seconds spent in each heart-rate zone for one activity — the actual effort distribution
    of a run (e.g. 80% Zone 2, 20% Zone 4), not just its single average HR number."""
    rows = conn.execute(
        """
        SELECT zone_number, zone_low_boundary_hr, seconds_in_zone
        FROM activity_hr_zones
        WHERE activity_id = ?
        ORDER BY zone_number
        """,
        (activity_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_activity_samples(
    conn: sqlite3.Connection, activity_id: int, max_points: int = 200
) -> List[Dict[str, Any]]:
    """Time-series pace/HR/cadence/elevation/temperature for one activity, evenly downsampled to
    at most `max_points` points — fine-grained enough to spot pacing consistency or HR drift
    (e.g. cardiac drift over a long run) at a finer resolution than 1km lap averages, without
    dumping thousands of raw rows into a single tool response.
    """
    max_points = _clamp(max_points, _MIN_LIMIT, _MAX_SAMPLE_POINTS)
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM activity_samples WHERE activity_id = ?", (activity_id,)
    ).fetchone()["n"]
    if total == 0:
        return []

    stride = max(1, -(-total // max_points))  # ceil(total / max_points)
    rows = conn.execute(
        """
        SELECT sample_index, elapsed_seconds, heart_rate, speed_mps, pace_sec_per_km,
               cadence_spm, elevation_meters, latitude, longitude, temperature_celsius
        FROM activity_samples
        WHERE activity_id = ? AND sample_index % ? = 0
        ORDER BY sample_index
        """,
        (activity_id, stride),
    ).fetchall()
    return [dict(row) for row in rows]


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
    auth = SharedSecretVerifier(settings.mcp_auth_token) if settings.mcp_auth_token else None
    if auth is None:
        logger.warning(
            "mcp_auth_token is not set — the MCP server is unauthenticated. Fine for LAN-only "
            "access; set mcp_auth_token before exposing this port beyond your LAN (e.g. via a "
            "Cloudflare Tunnel), since it serves personal Garmin activity/health data."
        )
    mcp: FastMCP = FastMCP("StrideSync", auth=auth)

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
    def training_baseline() -> Dict[str, Any]:
        """Get the athlete's current lactate threshold HR/pace and Garmin's own race-time
        predictions (5k/10k/half/marathon). Check this before answering questions about target
        pace or target heart rate — it's the reference point that turns a raw number like
        "average HR 150" into an actual effort level (easy/threshold/hard) for this person.
        Returns {"status": "unavailable"} if this account/device doesn't have this data.
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return get_training_baseline(conn)
        finally:
            conn.close()

    @mcp.tool()
    def activity_hr_zones(activity_id: int) -> List[Dict[str, Any]]:
        """Get seconds spent in each heart-rate zone for one activity — shows the actual effort
        distribution of a run (e.g. 80% Zone 2, 20% Zone 4), not just its single average HR.

        Args:
            activity_id: The activity's id, from `recent_activities`.
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return get_activity_hr_zones(conn, activity_id)
        finally:
            conn.close()

    @mcp.tool()
    def activity_samples(activity_id: int, max_points: int = 200) -> List[Dict[str, Any]]:
        """Get a time-series of pace/HR/cadence/elevation within one activity, evenly
        downsampled to at most max_points points. Use this for finer-grained pacing/HR-drift
        analysis (e.g. detecting cardiac drift over a long run, or precise negative splits) than
        1km lap averages allow.

        Args:
            activity_id: The activity's id, from `recent_activities`.
            max_points: Maximum number of time-series points to return (1-500, default 200).
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return get_activity_samples(conn, activity_id, max_points)
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
