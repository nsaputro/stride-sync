"""Sync scheduler entry point — python3 -m app.sync.scheduler [--once]

Runs as the sync-scheduler s6 service (rootfs/etc/services.d/sync-scheduler/run), polling Garmin
Connect every `sync_interval_hours` (default 6). See PROJECT_PLAN.md §1 (Scheduled sync service)
and milestone v0.2. `--once` remains for manual CLI verification (milestone v0.1).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sqlite3
import threading
from datetime import datetime, timezone
from types import FrameType
from typing import Callable, Optional, Sequence

from app import db
from app.config import Settings
from app.sync.garmin_client import (
    ActivitySample,
    GarminActivity,
    GarminAPIError,
    GarminAuthError,
    GarminClient,
    GarminLap,
    HrZoneTime,
    TrainingBaseline,
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


def _replace_hr_zones(
    conn: sqlite3.Connection, activity_id: int, zones: Sequence[HrZoneTime]
) -> None:
    conn.execute("DELETE FROM activity_hr_zones WHERE activity_id = ?", (activity_id,))
    conn.executemany(
        """
        INSERT INTO activity_hr_zones (
            activity_id, zone_number, zone_low_boundary_hr, seconds_in_zone
        ) VALUES (:activity_id, :zone_number, :zone_low_boundary_hr, :seconds_in_zone)
        """,
        [zone.__dict__ for zone in zones],
    )


def _replace_samples(
    conn: sqlite3.Connection, activity_id: int, samples: Sequence[ActivitySample]
) -> None:
    conn.execute("DELETE FROM activity_samples WHERE activity_id = ?", (activity_id,))
    conn.executemany(
        """
        INSERT INTO activity_samples (
            activity_id, sample_index, elapsed_seconds, heart_rate, speed_mps, pace_sec_per_km,
            cadence_spm, elevation_meters, latitude, longitude, temperature_celsius
        ) VALUES (
            :activity_id, :sample_index, :elapsed_seconds, :heart_rate, :speed_mps,
            :pace_sec_per_km, :cadence_spm, :elevation_meters, :latitude, :longitude,
            :temperature_celsius
        )
        """,
        [sample.__dict__ for sample in samples],
    )


def _upsert_training_baseline(
    conn: sqlite3.Connection, baseline: Optional[TrainingBaseline], synced_at: str
) -> None:
    """No-op if `baseline` is `None` — see `GarminClient.fetch_training_baseline`'s docstring:
    not every account has this data, and that's not treated as a sync failure."""
    if baseline is None:
        return
    conn.execute(
        """
        INSERT INTO training_baseline (
            id, synced_at, lactate_threshold_hr, lactate_threshold_speed_mps,
            lactate_threshold_pace_sec_per_km, race_prediction_5k_seconds,
            race_prediction_10k_seconds, race_prediction_half_marathon_seconds,
            race_prediction_marathon_seconds
        ) VALUES (
            1, :synced_at, :lactate_threshold_hr, :lactate_threshold_speed_mps,
            :lactate_threshold_pace_sec_per_km, :race_prediction_5k_seconds,
            :race_prediction_10k_seconds, :race_prediction_half_marathon_seconds,
            :race_prediction_marathon_seconds
        )
        ON CONFLICT (id) DO UPDATE SET
            synced_at = excluded.synced_at,
            lactate_threshold_hr = excluded.lactate_threshold_hr,
            lactate_threshold_speed_mps = excluded.lactate_threshold_speed_mps,
            lactate_threshold_pace_sec_per_km = excluded.lactate_threshold_pace_sec_per_km,
            race_prediction_5k_seconds = excluded.race_prediction_5k_seconds,
            race_prediction_10k_seconds = excluded.race_prediction_10k_seconds,
            race_prediction_half_marathon_seconds = excluded.race_prediction_half_marathon_seconds,
            race_prediction_marathon_seconds = excluded.race_prediction_marathon_seconds
        """,
        {**baseline.__dict__, "synced_at": synced_at},
    )


def _sync_activities(
    conn: sqlite3.Connection,
    client: GarminClient,
    activities: Sequence[GarminActivity],
    synced_at: str,
):
    """Write a fetched activity list (with laps/HR-zones/samples) to the DB, one at a time —
    shared by `run_sync_once` and `run_backfill_sync`, which only differ in how the activity
    list itself was fetched (most-recent-N vs. a date range) and whether `training_baseline`
    gets refreshed.

    A generator (yields once per completed activity) rather than returning a final count, so a
    caller iterating it still knows how many completed even if a later activity's fetch raises
    partway through — matching the "partial progress is still recorded in sync_log" behavior
    this already had before being extracted into its own function.
    """
    for activity in activities:
        _upsert_activity(conn, activity, synced_at)
        laps = client.fetch_activity_laps(activity.activity_id)
        _replace_laps(conn, activity.activity_id, laps)
        hr_zones = client.fetch_activity_hr_zones(activity.activity_id)
        _replace_hr_zones(conn, activity.activity_id, hr_zones)
        samples = client.fetch_activity_samples(activity.activity_id)
        _replace_samples(conn, activity.activity_id, samples)
        yield


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
        _upsert_training_baseline(conn, client.fetch_training_baseline(), synced_at)
        for _ in _sync_activities(conn, client, activities, synced_at):
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


def run_backfill_sync(
    settings: Settings,
    client: GarminClient,
    start_date: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> int:
    """One-off backfill: fetch every activity from `start_date` through today and write it the
    same way a regular sync does — a separate entry point from `run_sync_once` (see
    PROJECT_PLAN.md milestone v0.8) since it's date-based rather than count-based, and can cover
    far more activities in one call. Does not refresh `training_baseline` — that stays the
    regular scheduled sync's job.

    Args:
        progress_callback: If given, called as `progress_callback(completed, total)` — once
            immediately after the activity list is fetched (`completed=0`, so a caller showing a
            progress bar knows the total right away rather than waiting for the first activity
            to finish), then once per completed activity. A large date range can cover hundreds
            of activities and take a long time; this is how `app/mfa_web/server.py`'s Settings
            tab reports live progress instead of the caller just staring at a blank page.

    Returns:
        Number of activities backfilled.

    Raises:
        ValueError: if `start_date` isn't a valid `YYYY-MM-DD` date — raised by
            `client.fetch_activities_since` before any network call, so nothing is written or
            logged to `sync_log` for this case; it's a caller-input error, not a sync attempt.
        GarminAuthError: if login fails.
        GarminAPIError: if fetching activities or per-activity detail fails.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    conn = db.connect(settings.db_path)
    activities_synced = 0

    try:
        client.login()
        activities = client.fetch_activities_since(start_date)
        if progress_callback:
            progress_callback(0, len(activities))

        synced_at = datetime.now(timezone.utc).isoformat()
        for _ in _sync_activities(conn, client, activities, synced_at):
            activities_synced += 1
            if progress_callback:
                progress_callback(activities_synced, len(activities))
        conn.commit()
    except (GarminAuthError, GarminAPIError) as exc:
        conn.execute(
            """
            INSERT INTO sync_log (started_at, finished_at, status, activities_synced, error_message)
            VALUES (?, ?, 'failed', ?, ?)
            """,
            (
                started_at,
                datetime.now(timezone.utc).isoformat(),
                activities_synced,
                f"Backfill since {start_date} failed: {exc}",
            ),
        )
        conn.commit()
        logger.error("StrideSync backfill since %s failed: %s", start_date, exc)
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
        logger.info(
            "StrideSync backfill since %s succeeded: %d activities", start_date, activities_synced
        )
    finally:
        conn.close()

    return activities_synced


def run_forever(
    settings: Settings,
    make_client: Callable[[], GarminClient],
    limit: int = 20,
    interval_seconds: Optional[float] = None,
    stop_event: Optional[threading.Event] = None,
    max_iterations: Optional[int] = None,
) -> None:
    """Sync on a loop, once per `interval_seconds` (default: `settings.sync_interval_hours`).

    A failed sync (bad credentials, broken SSO, network error) is logged and recorded in
    `sync_log` by `run_sync_once` but never crashes this loop — the next scheduled sync is the
    retry, which is already a conservative backoff (PROJECT_PLAN.md's "known risk" section warns
    against retry storms; waiting a full interval between attempts avoids that by construction).

    Args:
        make_client: Builds a fresh GarminClient for each sync pass.
        interval_seconds: Overrides `settings.sync_interval_hours` — used by tests.
        stop_event: Signaled to stop the loop promptly instead of waiting out the full interval
            (see `_install_shutdown_handler`, which wires this to SIGTERM/SIGINT in `main()`).
        max_iterations: Stop after this many sync passes — used by tests; production runs
            forever.
    """
    if interval_seconds is None:
        interval_seconds = settings.sync_interval_hours * 3600
    stop_event = stop_event if stop_event is not None else threading.Event()

    iterations = 0
    while True:
        try:
            run_sync_once(settings, make_client(), limit=limit)
        except (GarminAuthError, GarminAPIError):
            pass  # already logged + recorded in sync_log; retry on the next interval

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            return
        if stop_event.wait(timeout=interval_seconds):
            return


def _install_shutdown_handler(stop_event: threading.Event) -> None:
    """Make SIGTERM/SIGINT set `stop_event` instead of killing the process mid-sleep.

    Without this, s6 stopping the service would otherwise leave the loop blocked in
    `stop_event.wait()` for up to `sync_interval_hours`, forcing a slow/forced container stop.
    """

    def _handle(signum: int, _frame: Optional[FrameType]) -> None:
        logger.info("Received signal %s, shutting down sync scheduler...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="StrideSync Garmin Connect sync")
    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "Run a single sync pass and exit, instead of looping on sync_interval_hours. "
            "Used for manual CLI verification (see PROJECT_PLAN.md milestone v0.1)."
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

    if not settings.garmin_username or not settings.garmin_password:
        parser.error("GARMIN_USERNAME and GARMIN_PASSWORD must be set")

    def make_client() -> GarminClient:
        return GarminClient(
            settings.garmin_username, settings.garmin_password, token_dir=settings.garmin_token_dir
        )

    if args.once:
        try:
            count = run_sync_once(settings, make_client(), limit=args.limit)
        except (GarminAuthError, GarminAPIError):
            return 1
        print(f"Synced {count} activities to {settings.db_path}")
        return 0

    logger.info(
        "Starting StrideSync sync scheduler: every %d hour(s)", settings.sync_interval_hours
    )
    stop_event = threading.Event()
    _install_shutdown_handler(stop_event)
    run_forever(settings, make_client, limit=args.limit, stop_event=stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
