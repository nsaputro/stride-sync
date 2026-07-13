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


def find_activities(
    conn: sqlite3.Connection,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    activity_type: Optional[str] = None,
    min_distance_meters: Optional[float] = None,
    max_distance_meters: Optional[float] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Activities matching all given filters, newest first — for locating a specific run or set
    of runs (e.g. "my long runs over 20km in June") rather than always pulling the most recent N
    like `recent_activities`. Every filter is optional and combines with AND; passing none of
    them behaves exactly like `recent_activities`.
    """
    limit = _clamp(limit, _MIN_LIMIT, _MAX_LIMIT)
    clauses = []
    params: List[Any] = []
    if start_date is not None:
        clauses.append("date(start_time_local) >= date(?)")
        params.append(start_date)
    if end_date is not None:
        clauses.append("date(start_time_local) <= date(?)")
        params.append(end_date)
    if activity_type is not None:
        clauses.append("activity_type = ? COLLATE NOCASE")
        params.append(activity_type)
    if min_distance_meters is not None:
        clauses.append("distance_meters >= ?")
        params.append(min_distance_meters)
    if max_distance_meters is not None:
        clauses.append("distance_meters <= ?")
        params.append(max_distance_meters)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT activity_id, activity_name, activity_type, start_time_local, duration_seconds,
               distance_meters, average_pace_sec_per_km, average_hr, max_hr,
               average_cadence_spm, max_cadence_spm, elevation_gain_meters, calories,
               aerobic_training_effect, anaerobic_training_effect, training_effect_label,
               activity_training_load
        FROM activities
        {where_sql}
        ORDER BY start_time_local DESC
        LIMIT ?
        """,
        params,
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


def get_daily_wellness(conn: sqlite3.Connection, days: int = 14) -> List[Dict[str, Any]]:
    """Sleep/HRV/training-status/readiness/resting-HR/training-load for the last N calendar
    dates, oldest first — see PROJECT_PLAN.md milestone v0.12. These are the earliest signals of
    overreaching, ahead of it ever showing up as declining pace or rising HR at the same effort
    in `pace_cadence_hr_trend`. Any field can be `None` for a given date — see
    `GarminClient.fetch_daily_wellness`'s docstring for why (not every endpoint/device/account
    reports every field).

    `acute_training_load`/`chronic_training_load`/`training_stress_balance` (chronic - acute,
    positive = fresher, negative = more fatigued) /`acute_chronic_workload_ratio` are Garmin's
    own fitness/fatigue framework (see PROJECT_PLAN.md milestone Stage 26) — a complementary,
    day-by-day view alongside `training_load_summary`'s window-aggregate numbers.
    """
    days = _clamp(days, _MIN_DAYS, _MAX_DAYS)
    rows = conn.execute(
        """
        SELECT calendar_date, sleep_score, sleep_duration_seconds, deep_sleep_seconds,
               light_sleep_seconds, rem_sleep_seconds, awake_sleep_seconds, hrv_status,
               hrv_weekly_avg_ms, hrv_last_night_avg_ms, training_status_label,
               training_readiness_score, resting_hr, acute_training_load, chronic_training_load,
               training_stress_balance, acute_chronic_workload_ratio
        FROM daily_wellness
        WHERE calendar_date >= date('now', '-' || ? || ' days')
        ORDER BY calendar_date ASC
        """,
        (days,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_resting_hr_trend(conn: sqlite3.Connection, days: int = 30) -> List[Dict[str, Any]]:
    """Resting HR for the last N days, oldest first, as (calendar_date, resting_hr) pairs — a
    rising resting HR over days/weeks is a classic early fatigue/illness signal.
    """
    days = _clamp(days, _MIN_DAYS, _MAX_DAYS)
    rows = conn.execute(
        """
        SELECT calendar_date, resting_hr
        FROM daily_wellness
        WHERE calendar_date >= date('now', '-' || ? || ' days')
        ORDER BY calendar_date ASC
        """,
        (days,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_vo2max_trend(conn: sqlite3.Connection, days: int = 90) -> List[Dict[str, Any]]:
    """VO2 max (running/cycling) and fitness age over the last N days, oldest first —
    additive to `training_baseline`, not a replacement. Default window is longer than other
    trend tools (90 vs. 30 days) since VO2 max moves slowly.
    """
    days = _clamp(days, _MIN_DAYS, _MAX_DAYS)
    rows = conn.execute(
        """
        SELECT calendar_date, vo2_max_running, vo2_max_cycling, fitness_age
        FROM vo2max_history
        WHERE calendar_date >= date('now', '-' || ? || ' days')
        ORDER BY calendar_date ASC
        """,
        (days,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_planned_vs_actual(conn: sqlite3.Connection, days: int = 14) -> List[Dict[str, Any]]:
    """Planned workouts from an active Garmin Connect training plan, LEFT JOINed against
    completed activities by calendar date — see PROJECT_PLAN.md milestone v0.12.

    Only returns dates with a planned workout; an account with no active plan gets `[]`, not an
    error. A day with multiple completed activities yields one row per match (rare, not
    deduplicated). `actual_*` fields are `None` when nothing was logged for that planned date.
    """
    days = _clamp(days, _MIN_DAYS, _MAX_DAYS)
    rows = conn.execute(
        """
        SELECT
            pw.workout_date, pw.workout_name, pw.workout_type, pw.planned_distance_meters,
            pw.planned_duration_seconds, pw.planned_target_pace_sec_per_km,
            pw.planned_target_hr_low, pw.planned_target_hr_high,
            a.activity_id, a.activity_name, a.activity_type,
            a.distance_meters AS actual_distance_meters,
            a.duration_seconds AS actual_duration_seconds,
            a.average_pace_sec_per_km AS actual_average_pace_sec_per_km,
            a.average_hr AS actual_average_hr
        FROM planned_workouts pw
        LEFT JOIN activities a ON date(a.start_time_local) = pw.workout_date
        WHERE pw.workout_date >= date('now', '-' || ? || ' days')
        ORDER BY pw.workout_date ASC
        """,
        (days,),
    ).fetchall()
    return [dict(row) for row in rows]


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
    def search_activities(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        activity_type: Optional[str] = None,
        min_distance_meters: Optional[float] = None,
        max_distance_meters: Optional[float] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Find activities matching a date range, type, and/or distance range, newest first.
        Use this instead of `recent_activities` when looking for a specific run or set of runs
        (e.g. "my runs over 20km in June", "cycling activities last week") rather than just the
        most recent N. Every filter is optional and combines with AND.

        Args:
            start_date: Only include activities on/after this calendar date (YYYY-MM-DD).
            end_date: Only include activities on/before this calendar date (YYYY-MM-DD).
            activity_type: Exact activity type to match (e.g. "running", "cycling"),
                case-insensitive.
            min_distance_meters: Only include activities at least this long.
            max_distance_meters: Only include activities at most this long.
            limit: Maximum number of activities to return (1-200, default 20).
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return find_activities(
                conn,
                start_date,
                end_date,
                activity_type,
                min_distance_meters,
                max_distance_meters,
                limit,
            )
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
    def daily_wellness(days: int = 14) -> List[Dict[str, Any]]:
        """Get sleep, HRV, Garmin's own training-status label and training-readiness score,
        resting HR, and day-by-day training load (acute/chronic/training-stress-balance/ACWR)
        for each of the last N calendar dates, oldest first. These are the earliest signals of
        overreaching — check this before assuming declining pace or rising HR is purely a
        fitness issue.

        Args:
            days: Number of days to look back (1-365, default 14).
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return get_daily_wellness(conn, days)
        finally:
            conn.close()

    @mcp.tool()
    def resting_hr_trend(days: int = 30) -> List[Dict[str, Any]]:
        """Get resting heart rate for each of the last N days, oldest first. A rising resting HR
        over days/weeks is a classic early fatigue/illness signal, often visible before it shows
        up in pace or effort during activities.

        Args:
            days: Number of days to look back (1-365, default 30).
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return get_resting_hr_trend(conn, days)
        finally:
            conn.close()

    @mcp.tool()
    def vo2max_trend(days: int = 90) -> List[Dict[str, Any]]:
        """Get VO2 max (running/cycling) and fitness age for each of the last N days, oldest
        first — additive to `training_baseline`'s current-value snapshot, showing whether
        fitness is actually improving through a training block rather than just today's number.

        Args:
            days: Number of days to look back (1-365, default 90 — VO2 max moves slowly).
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return get_vo2max_trend(conn, days)
        finally:
            conn.close()

    @mcp.tool()
    def planned_vs_actual(days: int = 14) -> List[Dict[str, Any]]:
        """Get planned workouts from an active Garmin Connect training plan compared against
        what was actually logged, for each of the last N days. Returns [] if this account has no
        active training plan configured — that's expected, not an error. This is the most
        speculative of StrideSync's tools: Garmin's training-plan field mappings are unverified
        against a live account, unlike everything else in this server.

        Args:
            days: Number of days to look back (1-365, default 14).
        """
        conn = _connect_readonly(settings.db_path)
        try:
            return get_planned_vs_actual(conn, days)
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
