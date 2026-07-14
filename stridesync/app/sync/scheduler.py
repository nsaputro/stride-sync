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
from datetime import datetime, timedelta, timezone
from types import FrameType
from typing import Callable, Optional, Sequence, Set

from app import db
from app.config import Settings
from app.sync.garmin_client import (
    ActivitySample,
    DailyWellness,
    GarminActivity,
    GarminAPIError,
    GarminAuthError,
    GarminClient,
    GarminLap,
    HrZoneTime,
    PlannedWorkout,
    TrainingBaseline,
    Vo2MaxReading,
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


# Today + previous 3 days — Garmin sometimes finalizes sleep/HRV data a day late, so re-fetching
# a small rolling window on every sync (not just today) catches that without tracking state.
_WELLNESS_WINDOW_DAYS = 4


def _upsert_daily_wellness(
    conn: sqlite3.Connection, wellness: DailyWellness, synced_at: str
) -> None:
    """One row per calendar date — always called with a real `DailyWellness` (see
    `GarminClient.fetch_daily_wellness`'s docstring: unlike `fetch_training_baseline`, it never
    returns `None`, so there is no no-op case here to guard against)."""
    conn.execute(
        """
        INSERT INTO daily_wellness (
            calendar_date, synced_at, sleep_score, sleep_duration_seconds, deep_sleep_seconds,
            light_sleep_seconds, rem_sleep_seconds, awake_sleep_seconds, hrv_status,
            hrv_weekly_avg_ms, hrv_last_night_avg_ms, training_status_label,
            training_readiness_score, resting_hr, acute_training_load, chronic_training_load,
            training_stress_balance, acute_chronic_workload_ratio, body_battery_charged,
            body_battery_drained, stress_avg, stress_max, respiration_waking_avg,
            respiration_sleep_avg
        ) VALUES (
            :calendar_date, :synced_at, :sleep_score, :sleep_duration_seconds,
            :deep_sleep_seconds, :light_sleep_seconds, :rem_sleep_seconds, :awake_sleep_seconds,
            :hrv_status, :hrv_weekly_avg_ms, :hrv_last_night_avg_ms, :training_status_label,
            :training_readiness_score, :resting_hr, :acute_training_load,
            :chronic_training_load, :training_stress_balance, :acute_chronic_workload_ratio,
            :body_battery_charged, :body_battery_drained, :stress_avg, :stress_max,
            :respiration_waking_avg, :respiration_sleep_avg
        )
        ON CONFLICT (calendar_date) DO UPDATE SET
            synced_at = excluded.synced_at,
            sleep_score = excluded.sleep_score,
            sleep_duration_seconds = excluded.sleep_duration_seconds,
            deep_sleep_seconds = excluded.deep_sleep_seconds,
            light_sleep_seconds = excluded.light_sleep_seconds,
            rem_sleep_seconds = excluded.rem_sleep_seconds,
            awake_sleep_seconds = excluded.awake_sleep_seconds,
            hrv_status = excluded.hrv_status,
            hrv_weekly_avg_ms = excluded.hrv_weekly_avg_ms,
            hrv_last_night_avg_ms = excluded.hrv_last_night_avg_ms,
            training_status_label = excluded.training_status_label,
            training_readiness_score = excluded.training_readiness_score,
            resting_hr = excluded.resting_hr,
            acute_training_load = excluded.acute_training_load,
            chronic_training_load = excluded.chronic_training_load,
            training_stress_balance = excluded.training_stress_balance,
            acute_chronic_workload_ratio = excluded.acute_chronic_workload_ratio,
            body_battery_charged = excluded.body_battery_charged,
            body_battery_drained = excluded.body_battery_drained,
            stress_avg = excluded.stress_avg,
            stress_max = excluded.stress_max,
            respiration_waking_avg = excluded.respiration_waking_avg,
            respiration_sleep_avg = excluded.respiration_sleep_avg
        """,
        {**wellness.__dict__, "synced_at": synced_at},
    )


def _upsert_vo2max(
    conn: sqlite3.Connection, reading: Optional[Vo2MaxReading], synced_at: str
) -> None:
    """No-op if `reading` is `None` — see `GarminClient.fetch_vo2max`'s docstring: not every
    device estimates VO2 max, and that's not treated as a sync failure."""
    if reading is None:
        return
    conn.execute(
        """
        INSERT INTO vo2max_history (
            calendar_date, synced_at, vo2_max_running, vo2_max_cycling, fitness_age
        ) VALUES (:calendar_date, :synced_at, :vo2_max_running, :vo2_max_cycling, :fitness_age)
        ON CONFLICT (calendar_date) DO UPDATE SET
            synced_at = excluded.synced_at,
            vo2_max_running = excluded.vo2_max_running,
            vo2_max_cycling = excluded.vo2_max_cycling,
            fitness_age = excluded.fitness_age
        """,
        {**reading.__dict__, "synced_at": synced_at},
    )


# Rolling ±14-day window for planned_workouts — lookback so a just-missed workout is still
# visible for comparison, lookahead so an upcoming plan is visible before it's due. Matches
# planned_vs_actual's default `days=14`.
_PLANNED_WORKOUT_LOOKBACK_DAYS = 14
_PLANNED_WORKOUT_LOOKAHEAD_DAYS = 14


def _replace_planned_workouts(
    conn: sqlite3.Connection,
    covered_dates: Set[str],
    workouts: Sequence[PlannedWorkout],
    synced_at: str,
) -> None:
    """Delete-then-bulk-insert, scoped to exactly `covered_dates` — not an UPSERT, since
    Garmin's training-plan response has no confirmed stable per-workout id to key one on (see
    `PlannedWorkout`'s docstring).

    `covered_dates` (from `GarminClient.fetch_planned_workouts`) is the set of calendar dates
    this sync's fetch actually got a definitive, still-changeable answer for — confirmed live,
    `taskList` is only ever a small rolling window of the current/upcoming days (~7 entries, not
    the full multi-week plan) no matter how wide a window was requested, and already-*completed*
    days are excluded even from that window (see `_normalize_planned_workouts`'s docstring) since
    a completed day's row must never be touched again and can simply stop appearing in later
    responses entirely. An earlier version of this function deleted the *entire* requested
    `[start_date, end_date]` window regardless of how much of it Garmin actually re-answered,
    silently wiping out any other week's already-synced rows with nothing to replace them —
    `covered_dates` fixes that by scoping the DELETE to only the dates this call actually has
    fresh, not-yet-completed data for (including rest-day dates, so a day that flips from
    "workout" to "rest day" still clears its stale row even though rest days aren't stored as
    rows themselves). An empty `covered_dates` (e.g. a transient fetch failure) is a no-op —
    nothing is known to be stale, so nothing is touched.
    """
    if not covered_dates:
        return
    placeholders = ",".join("?" for _ in covered_dates)
    conn.execute(
        f"DELETE FROM planned_workouts WHERE workout_date IN ({placeholders})",
        sorted(covered_dates),
    )
    conn.executemany(
        """
        INSERT INTO planned_workouts (
            plan_id, workout_date, workout_name, workout_type, planned_distance_meters,
            planned_duration_seconds, planned_target_pace_sec_per_km, planned_target_hr_low,
            planned_target_hr_high, synced_at
        ) VALUES (
            :plan_id, :workout_date, :workout_name, :workout_type, :planned_distance_meters,
            :planned_duration_seconds, :planned_target_pace_sec_per_km, :planned_target_hr_low,
            :planned_target_hr_high, :synced_at
        )
        """,
        [{**workout.__dict__, "synced_at": synced_at} for workout in workouts],
    )


def _sync_activities(
    conn: sqlite3.Connection,
    client: GarminClient,
    activities: Sequence[GarminActivity],
    synced_at: str,
):
    """Write a fetched activity list (with laps/HR-zones/samples) to the DB, one at a time —
    shared by `run_sync_once` and `run_backfill_sync`, which only differ in which date range the
    activity list itself was fetched for (since the last successful sync vs. an explicit
    caller-given start date) and whether `training_baseline`/`daily_wellness`/`vo2max_history`/
    `planned_workouts` get refreshed.

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


# Fallback lookback window for the very first sync an account ever runs, when there is no prior
# successful sync_log row to compute an incremental start date from.
_FIRST_SYNC_LOOKBACK_DAYS = 7


def _last_successful_sync_date(conn: sqlite3.Connection) -> Optional[str]:
    """Calendar date (`YYYY-MM-DD`) of the most recent successful sync, or `None` if this
    account has never completed one yet.

    Used by `run_sync_once` to fetch activities incrementally (since that date) instead of a
    fixed most-recent-N cutoff — a fixed count silently misses activities on a busy stretch (more
    than N logged since the last sync) and re-fetches everything again on a quiet one. `started_at`
    (not `finished_at`) is used deliberately: a failed sync still moved forward in time attempting
    one, so the next attempt should re-cover from the same starting point rather than skip ahead
    past whatever it failed to sync.
    """
    row = conn.execute(
        "SELECT started_at FROM sync_log WHERE status = 'success' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return row["started_at"][:10]


def run_sync_once(settings: Settings, client: GarminClient) -> int:
    """Run a single sync pass: login, fetch activities since the last successful sync + laps,
    write to SQLite.

    Activities are fetched incrementally — since the previous successful sync's date, or
    `_FIRST_SYNC_LOOKBACK_DAYS` (7) days back if this account has never synced successfully
    before — rather than a fixed most-recent-N count, so a busy stretch (more activities logged
    than a fixed count would cover) is never silently missed.

    Records the outcome in `sync_log` regardless of success or failure (CLAUDE.md: "Fail loud,
    not silent" — a broken sync must never leave the database looking current without a trace).
    Every record type's count (activities, daily_wellness, vo2max_history, planned_workouts) is
    logged on both the success and failure path, so an add-on log line alone is enough to confirm
    what actually got synced without needing to query the database directly.

    Returns:
        Number of activities synced.

    Raises:
        GarminAuthError: if login fails.
        GarminAPIError: if fetching activities or laps fails after a successful login.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    conn = db.connect(settings.db_path)
    activities_synced = 0
    wellness_synced = 0
    vo2max_synced = 0
    planned_workouts_synced = 0

    try:
        client.login()
        today = datetime.now(timezone.utc).date()
        since_date = _last_successful_sync_date(conn) or (
            today - timedelta(days=_FIRST_SYNC_LOOKBACK_DAYS)
        ).isoformat()
        activities = client.fetch_activities_since(since_date)

        synced_at = datetime.now(timezone.utc).isoformat()
        _upsert_training_baseline(conn, client.fetch_training_baseline(), synced_at)
        for offset in range(_WELLNESS_WINDOW_DAYS):
            cdate = (today - timedelta(days=offset)).isoformat()
            _upsert_daily_wellness(conn, client.fetch_daily_wellness(cdate), synced_at)
            wellness_synced += 1
            vo2max_reading = client.fetch_vo2max(cdate)
            _upsert_vo2max(conn, vo2max_reading, synced_at)
            if vo2max_reading is not None:
                vo2max_synced += 1
        plan_start = (today - timedelta(days=_PLANNED_WORKOUT_LOOKBACK_DAYS)).isoformat()
        plan_end = (today + timedelta(days=_PLANNED_WORKOUT_LOOKAHEAD_DAYS)).isoformat()
        planned_workouts, planned_workout_dates = client.fetch_planned_workouts(
            plan_start, plan_end
        )
        _replace_planned_workouts(conn, planned_workout_dates, planned_workouts, synced_at)
        planned_workouts_synced = len(planned_workouts)

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
        logger.error(
            "StrideSync sync failed: %s (partial progress before failure: %d activities, "
            "%d wellness records, %d vo2max records, %d planned workouts)",
            exc,
            activities_synced,
            wellness_synced,
            vo2max_synced,
            planned_workouts_synced,
        )
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
            "StrideSync sync succeeded: %d activities, %d wellness records, %d vo2max records, "
            "%d planned workouts",
            activities_synced,
            wellness_synced,
            vo2max_synced,
            planned_workouts_synced,
        )
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
    PROJECT_PLAN.md milestone v0.8) since it takes an explicit caller-given start date that can
    reach arbitrarily far into the past, rather than `run_sync_once`'s implicit "since the last
    successful sync" range (see milestone v0.13), and so can cover far more activities in one
    call.

    Also refreshes `training_baseline`, `daily_wellness`, `vo2max_history`, and
    `planned_workouts` — same as `run_sync_once`, just anchored to `start_date` instead of "since
    the last successful sync" (see milestone v0.14): `daily_wellness`/`vo2max_history` are
    fetched for every date from `start_date` through today (not `run_sync_once`'s fixed
    `_WELLNESS_WINDOW_DAYS`-day rolling window), since backfilling a wide historical range is the
    entire point of this entry point. `planned_workouts` isn't itself a historical concept (it's
    a forward-looking training plan), so it still uses the same fixed
    `[-_PLANNED_WORKOUT_LOOKBACK_DAYS, +_PLANNED_WORKOUT_LOOKAHEAD_DAYS]`-from-today window as
    `run_sync_once`, regardless of `start_date`. A wide date range means many extra Garmin API
    calls beyond the activities themselves (5 wellness/vo2max calls per day in range) — expect a
    multi-year backfill to take noticeably longer than before this milestone.

    Args:
        progress_callback: If given, called as `progress_callback(completed, total)` — once
            immediately after the activity list is fetched (`completed=0`, so a caller showing a
            progress bar knows the total right away rather than waiting for the first activity
            to finish), then once per completed activity. Note this only reflects the activities
            phase — the wellness/vo2max/planned_workouts phase (which runs first) has no progress
            callback of its own, so a caller's progress bar may sit at "0 / N" for a while before
            advancing on a wide date range. A large date range can cover hundreds of activities
            and take a long time; this is how `app/mfa_web/server.py`'s Settings tab reports live
            progress instead of the caller just staring at a blank page.

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
    wellness_synced = 0
    vo2max_synced = 0
    planned_workouts_synced = 0

    try:
        client.login()
        activities = client.fetch_activities_since(start_date)
        if progress_callback:
            progress_callback(0, len(activities))

        synced_at = datetime.now(timezone.utc).isoformat()
        _upsert_training_baseline(conn, client.fetch_training_baseline(), synced_at)

        # start_date is already confirmed valid YYYY-MM-DD by fetch_activities_since above --
        # stripped the same way its own internal validation tolerates surrounding whitespace.
        start = datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()
        cdate = start
        while cdate <= today:
            cdate_str = cdate.isoformat()
            _upsert_daily_wellness(conn, client.fetch_daily_wellness(cdate_str), synced_at)
            wellness_synced += 1
            vo2max_reading = client.fetch_vo2max(cdate_str)
            _upsert_vo2max(conn, vo2max_reading, synced_at)
            if vo2max_reading is not None:
                vo2max_synced += 1
            cdate += timedelta(days=1)

        plan_start = (today - timedelta(days=_PLANNED_WORKOUT_LOOKBACK_DAYS)).isoformat()
        plan_end = (today + timedelta(days=_PLANNED_WORKOUT_LOOKAHEAD_DAYS)).isoformat()
        planned_workouts, planned_workout_dates = client.fetch_planned_workouts(
            plan_start, plan_end
        )
        _replace_planned_workouts(conn, planned_workout_dates, planned_workouts, synced_at)
        planned_workouts_synced = len(planned_workouts)

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
        logger.error(
            "StrideSync backfill since %s failed: %s (partial progress before failure: "
            "%d activities, %d wellness records, %d vo2max records, %d planned workouts)",
            start_date,
            exc,
            activities_synced,
            wellness_synced,
            vo2max_synced,
            planned_workouts_synced,
        )
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
            "StrideSync backfill since %s succeeded: %d activities, %d wellness records, "
            "%d vo2max records, %d planned workouts",
            start_date,
            activities_synced,
            wellness_synced,
            vo2max_synced,
            planned_workouts_synced,
        )
    finally:
        conn.close()

    return activities_synced


def run_forever(
    settings: Settings,
    make_client: Callable[[], GarminClient],
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
            run_sync_once(settings, make_client())
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
            count = run_sync_once(settings, make_client())
        except (GarminAuthError, GarminAPIError):
            return 1
        print(f"Synced {count} activities to {settings.db_path}")
        return 0

    logger.info(
        "Starting StrideSync sync scheduler: every %d hour(s)", settings.sync_interval_hours
    )
    stop_event = threading.Event()
    _install_shutdown_handler(stop_event)
    run_forever(settings, make_client, stop_event=stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
