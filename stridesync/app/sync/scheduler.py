"""Sync scheduler entry point — python3 -m app.sync.scheduler --once

Runs as the sync-scheduler s6 service (rootfs/etc/services.d/sync-scheduler/run) from v0.2
onward. See PROJECT_PLAN.md §1 (Scheduled sync service) and milestone v0.1 (manual sync only —
the continuous interval loop is v0.2's `--daemon`-style entry, not yet implemented here).
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Sequence

from app import db
from app.config import Settings
from app.sync.garmin_client import (
    GarminActivity,
    GarminAPIError,
    GarminAuthError,
    GarminClient,
    GarminLap,
)

logger = logging.getLogger(__name__)


def _upsert_activity(conn: sqlite3.Connection, activity: GarminActivity, synced_at: str) -> None:
    conn.execute(
        """
        INSERT INTO activities (
            activity_id, activity_name, activity_type, start_time_local, start_time_gmt,
            duration_seconds, moving_duration_seconds, distance_meters, average_speed_mps,
            average_pace_sec_per_km, average_hr, max_hr, average_cadence_spm, max_cadence_spm,
            elevation_gain_meters, elevation_loss_meters, calories, aerobic_training_effect,
            anaerobic_training_effect, training_effect_label, activity_training_load, synced_at
        ) VALUES (
            :activity_id, :activity_name, :activity_type, :start_time_local, :start_time_gmt,
            :duration_seconds, :moving_duration_seconds, :distance_meters, :average_speed_mps,
            :average_pace_sec_per_km, :average_hr, :max_hr, :average_cadence_spm,
            :max_cadence_spm, :elevation_gain_meters, :elevation_loss_meters, :calories,
            :aerobic_training_effect, :anaerobic_training_effect, :training_effect_label,
            :activity_training_load, :synced_at
        )
        ON CONFLICT (activity_id) DO UPDATE SET
            activity_name = excluded.activity_name,
            activity_type = excluded.activity_type,
            start_time_local = excluded.start_time_local,
            start_time_gmt = excluded.start_time_gmt,
            duration_seconds = excluded.duration_seconds,
            moving_duration_seconds = excluded.moving_duration_seconds,
            distance_meters = excluded.distance_meters,
            average_speed_mps = excluded.average_speed_mps,
            average_pace_sec_per_km = excluded.average_pace_sec_per_km,
            average_hr = excluded.average_hr,
            max_hr = excluded.max_hr,
            average_cadence_spm = excluded.average_cadence_spm,
            max_cadence_spm = excluded.max_cadence_spm,
            elevation_gain_meters = excluded.elevation_gain_meters,
            elevation_loss_meters = excluded.elevation_loss_meters,
            calories = excluded.calories,
            aerobic_training_effect = excluded.aerobic_training_effect,
            anaerobic_training_effect = excluded.anaerobic_training_effect,
            training_effect_label = excluded.training_effect_label,
            activity_training_load = excluded.activity_training_load,
            synced_at = excluded.synced_at
        """,
        {**activity.__dict__, "synced_at": synced_at},
    )


def _replace_laps(conn: sqlite3.Connection, activity_id: int, laps: Sequence[GarminLap]) -> None:
    conn.execute("DELETE FROM activity_metrics WHERE activity_id = ?", (activity_id,))
    conn.executemany(
        """
        INSERT INTO activity_metrics (
            activity_id, lap_index, start_time_gmt, duration_seconds, distance_meters,
            average_speed_mps, pace_sec_per_km, average_hr, max_hr, average_cadence_spm,
            max_cadence_spm
        ) VALUES (
            :activity_id, :lap_index, :start_time_gmt, :duration_seconds, :distance_meters,
            :average_speed_mps, :pace_sec_per_km, :average_hr, :max_hr, :average_cadence_spm,
            :max_cadence_spm
        )
        """,
        [lap.__dict__ for lap in laps],
    )


def run_sync_once(settings: Settings, client: GarminClient, limit: int = 20) -> int:
    """Run a single sync pass: login, fetch recent activities + laps, write to SQLite.

    Records the outcome in `sync_log` regardless of success or failure (CLAUDE.md: "Fail loud,
    not silent" — a broken sync must never leave the database looking current without a trace).

    Returns:
        Number of activities synced.

    Raises:
        GarminAuthError: if login fails.
        GarminAPIError: if fetching activities or laps fails after a successful login.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    conn = db.connect(settings.db_path)
    activities_synced = 0

    try:
        client.login()
        activities = client.fetch_recent_activities(limit=limit)

        synced_at = datetime.now(timezone.utc).isoformat()
        for activity in activities:
            _upsert_activity(conn, activity, synced_at)
            laps = client.fetch_activity_laps(activity.activity_id)
            _replace_laps(conn, activity.activity_id, laps)
            activities_synced += 1
        conn.commit()
    except (GarminAuthError, GarminAPIError) as exc:
        conn.execute(
            """
            INSERT INTO sync_log (started_at, finished_at, status, activities_synced, error_message)
            VALUES (?, ?, 'failed', ?, ?)
            """,
            (started_at, datetime.now(timezone.utc).isoformat(), activities_synced, str(exc)),
        )
        conn.commit()
        logger.error("StrideSync sync failed: %s", exc)
        raise
    else:
        conn.execute(
            """
            INSERT INTO sync_log (started_at, finished_at, status, activities_synced, error_message)
            VALUES (?, ?, 'success', ?, NULL)
            """,
            (started_at, datetime.now(timezone.utc).isoformat(), activities_synced),
        )
        conn.commit()
        logger.info("StrideSync sync succeeded: %d activities", activities_synced)
    finally:
        conn.close()

    return activities_synced


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="StrideSync Garmin Connect sync")
    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "Run a single sync pass and exit (v0.1 CLI verification mode). Continuous "
            "interval-based scheduling is added in v0.2."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of recent activities to sync (default: 20).",
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    logging.basicConfig(level=settings.log_level.upper())

    if not args.once:
        parser.error(
            "continuous scheduling isn't implemented yet (see PROJECT_PLAN.md milestone v0.2) "
            "— run with --once for a manual sync"
        )

    if not settings.garmin_username or not settings.garmin_password:
        parser.error("GARMIN_USERNAME and GARMIN_PASSWORD must be set")

    client = GarminClient(settings.garmin_username, settings.garmin_password)

    try:
        count = run_sync_once(settings, client, limit=args.limit)
    except (GarminAuthError, GarminAPIError):
        return 1

    print(f"Synced {count} activities to {settings.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
