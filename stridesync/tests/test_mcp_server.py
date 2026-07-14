import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from app import db
from app.mcp.server import (
    SharedSecretVerifier,
    _clamp,
    _connect_readonly,
    create_server,
    find_activities,
    get_activity_hr_zones,
    get_activity_laps,
    get_activity_samples,
    get_daily_wellness,
    get_last_sync_status,
    get_pace_cadence_hr_trend,
    get_planned_vs_actual,
    get_resting_hr_trend,
    get_training_baseline,
    get_training_load_summary,
    get_vo2max_trend,
    list_recent_activities,
)
from app.config import Settings


def make_settings(tmp_path) -> Settings:
    return Settings(
        garmin_username="user@example.com",
        garmin_password="hunter2",
        sync_interval_hours=6,
        mcp_port=8765,
        log_level="info",
        db_path=str(tmp_path / "stridesync.db"),
        garmin_token_dir=str(tmp_path / "garmin_tokens"),
        mfa_web_port=8767,
    )


def seed_db(db_path: str) -> None:
    conn = db.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO activities (
                activity_id, activity_name, activity_type, start_time_local, start_time_gmt,
                duration_seconds, distance_meters, average_pace_sec_per_km, average_hr, max_hr,
                average_cadence_spm, max_cadence_spm, elevation_gain_meters, calories,
                aerobic_training_effect, anaerobic_training_effect, training_effect_label,
                activity_training_load, synced_at
            ) VALUES (
                1, 'Morning Run', 'running', datetime('now', '-1 days'), datetime('now', '-1 days'),
                1800, 5000, 359.7, 150, 172, 170.0, 182.0, 45.0, 320.0, 3.2, 0.5, 'TEMPO', 85.0,
                datetime('now')
            )
            """
        )
        conn.execute(
            """
            INSERT INTO activities (
                activity_id, activity_name, activity_type, start_time_local, start_time_gmt,
                duration_seconds, distance_meters, average_pace_sec_per_km, average_hr, max_hr,
                average_cadence_spm, max_cadence_spm, elevation_gain_meters, calories,
                aerobic_training_effect, anaerobic_training_effect, training_effect_label,
                activity_training_load, synced_at
            ) VALUES (
                2, 'Old Run', 'running', datetime('now', '-100 days'), datetime('now', '-100 days'),
                1200, 3000, 400.0, 140, 160, 165.0, 175.0, 20.0, 200.0, 2.0, 0.2, 'BASE', 40.0,
                datetime('now')
            )
            """
        )
        conn.execute(
            """
            INSERT INTO activity_metrics (
                activity_id, lap_index, start_time_gmt, duration_seconds, distance_meters,
                average_speed_mps, pace_sec_per_km, average_hr, max_hr, average_cadence_spm,
                max_cadence_spm
            ) VALUES (1, 0, '2026-06-01 13:30:00', 300, 1000, 3.0, 333.3, 148, 160, 172.0, 178.0)
            """
        )
        conn.execute(
            """
            INSERT INTO sync_log (started_at, finished_at, status, activities_synced, error_message)
            VALUES ('2026-06-01T00:00:00+00:00', '2026-06-01T00:00:05+00:00', 'success', 2, NULL)
            """
        )
        conn.execute(
            """
            INSERT INTO training_baseline (
                id, synced_at, lactate_threshold_hr, lactate_threshold_speed_mps,
                lactate_threshold_pace_sec_per_km, race_prediction_5k_seconds,
                race_prediction_10k_seconds, race_prediction_half_marathon_seconds,
                race_prediction_marathon_seconds
            ) VALUES (1, datetime('now'), 165, 3.2, 312.5, 1200, 2500, 5600, 11800)
            """
        )
        conn.execute(
            """
            INSERT INTO activity_hr_zones (activity_id, zone_number, zone_low_boundary_hr, seconds_in_zone)
            VALUES (1, 1, 100, 120.0), (1, 2, 140, 900.0)
            """
        )
        conn.executemany(
            """
            INSERT INTO activity_samples (
                activity_id, sample_index, elapsed_seconds, heart_rate, speed_mps,
                pace_sec_per_km, cadence_spm, elevation_meters, latitude, longitude,
                temperature_celsius
            ) VALUES (1, ?, ?, ?, 2.78, 359.7, 170.0, 12.5, 37.0, -122.0, 18.5)
            """,
            [(i, float(i * 10), 150 + i) for i in range(5)],
        )
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
                date('now', '-1 days'), datetime('now'), 82, 27000.0, 5400.0, 14400.0, 6300.0,
                900.0, 'BALANCED', 55.0, 53.0, 'PRODUCTIVE', 78, 48, 420.5, 380.0, -40.5, 1.11,
                45.0, 60.0, 32, 68, 15.5, 13.2
            )
            """
        )
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
                date('now', '-100 days'), datetime('now'), 70, 24000.0, 4000.0, 13000.0, 5000.0,
                1200.0, 'LOW', 40.0, 38.0, 'RECOVERY', 60, 52, 300.0, 320.0, 20.0, 0.94,
                30.0, 55.0, 25, 50, 14.0, 12.0
            )
            """
        )
        conn.execute(
            """
            INSERT INTO vo2max_history (
                calendar_date, synced_at, vo2_max_running, vo2_max_cycling, fitness_age
            ) VALUES (date('now', '-1 days'), datetime('now'), 52.5, 48.0, 28)
            """
        )
        conn.execute(
            """
            INSERT INTO vo2max_history (
                calendar_date, synced_at, vo2_max_running, vo2_max_cycling, fitness_age
            ) VALUES (date('now', '-100 days'), datetime('now'), 48.0, 44.0, 32)
            """
        )
        conn.execute(
            """
            INSERT INTO planned_workouts (
                plan_id, workout_date, workout_name, workout_type, planned_distance_meters,
                planned_duration_seconds, planned_target_pace_sec_per_km,
                planned_target_hr_low, planned_target_hr_high, synced_at
            ) VALUES (
                'plan-1', date('now', '-1 days'), 'Tempo Run', 'tempo', 8000.0, 2400.0, 300.0,
                150, 165, datetime('now')
            )
            """
        )
        conn.execute(
            """
            INSERT INTO planned_workouts (
                plan_id, workout_date, workout_name, workout_type, planned_distance_meters,
                planned_duration_seconds, planned_target_pace_sec_per_km,
                planned_target_hr_low, planned_target_hr_high, synced_at
            ) VALUES (
                'plan-1', date('now', '-2 days'), 'Easy Run', 'easy', 5000.0, 1800.0, 360.0,
                130, 145, datetime('now')
            )
            """
        )
        conn.execute(
            """
            INSERT INTO planned_workouts (
                plan_id, workout_date, workout_name, workout_type, planned_distance_meters,
                planned_duration_seconds, planned_target_pace_sec_per_km,
                planned_target_hr_low, planned_target_hr_high, synced_at
            ) VALUES (
                'plan-1', date('now', '-100 days'), 'Old Plan Run', 'tempo', 8000.0, 2400.0,
                300.0, 150, 165, datetime('now')
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


class TestClamp:
    def test_within_range(self):
        assert _clamp(50, 1, 200) == 50

    def test_below_min(self):
        assert _clamp(0, 1, 200) == 1

    def test_above_max(self):
        assert _clamp(9999, 1, 200) == 200


class TestConnectReadonly:
    def test_rejects_writes(self, tmp_path):
        db_path = str(tmp_path / "stridesync.db")
        db.connect(db_path).close()  # create schema first

        conn = _connect_readonly(db_path)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("INSERT INTO sync_log (started_at, status) VALUES ('x', 'success')")
        finally:
            conn.close()

    def test_allows_reads(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)

        conn = _connect_readonly(settings.db_path)
        try:
            rows = conn.execute("SELECT COUNT(*) AS n FROM activities").fetchall()
            assert rows[0]["n"] == 2
        finally:
            conn.close()


class TestQueries:
    def test_list_recent_activities_orders_newest_first(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            activities = list_recent_activities(conn, limit=10)
            assert [a["activity_id"] for a in activities] == [1, 2]
            assert activities[0]["activity_name"] == "Morning Run"
            assert activities[0]["distance_meters"] == 5000
        finally:
            conn.close()

    def test_list_recent_activities_respects_limit(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            activities = list_recent_activities(conn, limit=1)
            assert len(activities) == 1
            assert activities[0]["activity_id"] == 1
        finally:
            conn.close()

    def test_get_activity_laps(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            laps = get_activity_laps(conn, 1)
            assert len(laps) == 1
            assert laps[0]["distance_meters"] == 1000
        finally:
            conn.close()

    def test_get_activity_laps_empty_for_unknown_activity(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            assert get_activity_laps(conn, 999) == []
        finally:
            conn.close()

    def test_pace_cadence_hr_trend_excludes_activities_outside_window(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            trend = get_pace_cadence_hr_trend(conn, days=30)
            # activity 2 is 100 days old — outside a 30-day window
            names = [row["activity_name"] for row in trend]
            assert names == ["Morning Run"]
        finally:
            conn.close()

    def test_pace_cadence_hr_trend_wide_window_includes_all(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            trend = get_pace_cadence_hr_trend(conn, days=365)
            assert len(trend) == 2
        finally:
            conn.close()

    def test_training_load_summary(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            summary = get_training_load_summary(conn, days=30)
            assert summary["activity_count"] == 1  # only "Morning Run" within 30 days
            assert summary["total_training_load"] == 85.0
            assert summary["period_days"] == 30
        finally:
            conn.close()

    def test_last_sync_status_returns_most_recent(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            status = get_last_sync_status(conn)
            assert status["status"] == "success"
            assert status["activities_synced"] == 2
        finally:
            conn.close()

    def test_last_sync_status_never_synced(self, tmp_path):
        settings = make_settings(tmp_path)
        db.connect(settings.db_path).close()  # schema only, no sync_log rows
        conn = db.connect(settings.db_path)
        try:
            assert get_last_sync_status(conn) == {"status": "never_synced"}
        finally:
            conn.close()

    def test_get_training_baseline(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            baseline = get_training_baseline(conn)
            assert baseline["lactate_threshold_hr"] == 165
            assert baseline["race_prediction_marathon_seconds"] == 11800
        finally:
            conn.close()

    def test_get_training_baseline_unavailable(self, tmp_path):
        settings = make_settings(tmp_path)
        db.connect(settings.db_path).close()  # schema only, no training_baseline row
        conn = db.connect(settings.db_path)
        try:
            assert get_training_baseline(conn) == {"status": "unavailable"}
        finally:
            conn.close()

    def test_daily_wellness_excludes_dates_outside_window(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            wellness = get_daily_wellness(conn, days=14)
            # the -100 days row is outside a 14-day window
            dates = [row["calendar_date"] for row in wellness]
            assert len(dates) == 1
            assert wellness[0]["sleep_score"] == 82
            assert wellness[0]["resting_hr"] == 48
            assert wellness[0]["acute_training_load"] == 420.5
            assert wellness[0]["chronic_training_load"] == 380.0
            assert wellness[0]["training_stress_balance"] == -40.5
            assert wellness[0]["acute_chronic_workload_ratio"] == 1.11
            assert wellness[0]["body_battery_charged"] == 45.0
            assert wellness[0]["body_battery_drained"] == 60.0
            assert wellness[0]["stress_avg"] == 32
            assert wellness[0]["stress_max"] == 68
            assert wellness[0]["respiration_waking_avg"] == 15.5
            assert wellness[0]["respiration_sleep_avg"] == 13.2
        finally:
            conn.close()

    def test_daily_wellness_wide_window_includes_all_oldest_first(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            wellness = get_daily_wellness(conn, days=365)
            assert len(wellness) == 2
            # oldest first
            assert wellness[0]["resting_hr"] == 52
            assert wellness[1]["resting_hr"] == 48
        finally:
            conn.close()

    def test_resting_hr_trend_excludes_dates_outside_window(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            trend = get_resting_hr_trend(conn, days=30)
            assert len(trend) == 1
            assert trend[0]["resting_hr"] == 48
        finally:
            conn.close()

    def test_vo2max_trend_excludes_dates_outside_window(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            trend = get_vo2max_trend(conn, days=30)
            assert len(trend) == 1
            assert trend[0]["vo2_max_running"] == 52.5
            assert trend[0]["fitness_age"] == 28
        finally:
            conn.close()

    def test_vo2max_trend_wide_window_includes_all_oldest_first(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            trend = get_vo2max_trend(conn, days=365)
            assert len(trend) == 2
            # oldest first
            assert trend[0]["fitness_age"] == 32
            assert trend[1]["fitness_age"] == 28
        finally:
            conn.close()

    def test_planned_vs_actual_joins_matching_activity(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            rows = get_planned_vs_actual(conn, days=14)
            # -100 days row is outside the window; -1 and -2 day rows remain, oldest first
            assert len(rows) == 2
            matched = next(r for r in rows if r["workout_name"] == "Tempo Run")
            assert matched["activity_id"] == 1
            assert matched["actual_distance_meters"] == 5000
        finally:
            conn.close()

    def test_planned_vs_actual_null_actuals_when_no_matching_activity(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            rows = get_planned_vs_actual(conn, days=14)
            unmatched = next(r for r in rows if r["workout_name"] == "Easy Run")
            assert unmatched["activity_id"] is None
            assert unmatched["actual_distance_meters"] is None
        finally:
            conn.close()

    def test_planned_vs_actual_excludes_workouts_outside_window(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            rows = get_planned_vs_actual(conn, days=14)
            names = {r["workout_name"] for r in rows}
            assert "Old Plan Run" not in names
        finally:
            conn.close()

    def test_planned_vs_actual_empty_table_returns_empty_list(self, tmp_path):
        settings = make_settings(tmp_path)
        db.connect(settings.db_path).close()  # schema only, no planned_workouts rows
        conn = db.connect(settings.db_path)
        try:
            assert get_planned_vs_actual(conn) == []
        finally:
            conn.close()

    def test_get_activity_hr_zones(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            zones = get_activity_hr_zones(conn, 1)
            assert len(zones) == 2
            assert zones[0]["zone_number"] == 1
            assert zones[1]["seconds_in_zone"] == 900.0
        finally:
            conn.close()

    def test_get_activity_hr_zones_empty_for_unknown_activity(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            assert get_activity_hr_zones(conn, 999) == []
        finally:
            conn.close()

    def test_get_activity_samples_returns_all_when_under_max_points(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            samples = get_activity_samples(conn, 1, max_points=200)
            assert len(samples) == 5
            assert samples[0]["heart_rate"] == 150
            assert samples[0]["temperature_celsius"] == 18.5
        finally:
            conn.close()

    def test_get_activity_samples_downsamples_when_over_max_points(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            samples = get_activity_samples(conn, 1, max_points=2)
            # 5 samples, stride = ceil(5/2) = 3 -> indices 0, 3
            assert [s["sample_index"] for s in samples] == [0, 3]
        finally:
            conn.close()

    def test_get_activity_samples_empty_for_unknown_activity(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            assert get_activity_samples(conn, 999) == []
        finally:
            conn.close()


class TestFindActivities:
    def test_no_filters_behaves_like_recent_activities(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            activities = find_activities(conn)
            assert [a["activity_id"] for a in activities] == [1, 2]
        finally:
            conn.close()

    def test_filters_by_date_range(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            # activity 1 is ~1 day old, activity 2 is ~100 days old.
            activities = find_activities(conn, start_date="2000-01-01", end_date="2100-01-01")
            assert len(activities) == 2

            recent_only = find_activities(
                conn,
                start_date=(datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat(),
            )
            assert [a["activity_id"] for a in recent_only] == [1]

            old_only = find_activities(
                conn,
                end_date=(datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat(),
            )
            assert [a["activity_id"] for a in old_only] == [2]
        finally:
            conn.close()

    def test_filters_by_activity_type_case_insensitive(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            conn.execute(
                """
                INSERT INTO activities (
                    activity_id, activity_name, activity_type, start_time_local,
                    start_time_gmt, duration_seconds, distance_meters, synced_at
                ) VALUES (
                    3, 'Evening Ride', 'cycling', datetime('now'), datetime('now'),
                    3600, 20000, datetime('now')
                )
                """
            )
            conn.commit()

            activities = find_activities(conn, activity_type="CYCLING")
            assert [a["activity_id"] for a in activities] == [3]
        finally:
            conn.close()

    def test_filters_by_distance_range(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            # activity 1: 5000m, activity 2: 3000m.
            activities = find_activities(conn, min_distance_meters=4000)
            assert [a["activity_id"] for a in activities] == [1]

            activities = find_activities(conn, max_distance_meters=4000)
            assert [a["activity_id"] for a in activities] == [2]
        finally:
            conn.close()

    def test_combines_filters_with_and(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            # activity 1 (5000m, recent) matches both; activity 2 (3000m) fails the distance
            # filter even though it'd otherwise match a wide-open date range.
            activities = find_activities(
                conn,
                start_date="2000-01-01",
                min_distance_meters=4000,
            )
            assert [a["activity_id"] for a in activities] == [1]
        finally:
            conn.close()

    def test_respects_limit(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        conn = db.connect(settings.db_path)
        try:
            activities = find_activities(conn, start_date="2000-01-01", limit=1)
            assert len(activities) == 1
            assert activities[0]["activity_id"] == 1
        finally:
            conn.close()


class TestSharedSecretVerifier:
    def test_accepts_correct_token(self):
        verifier = SharedSecretVerifier("s3cr3t")

        result = asyncio.run(verifier.verify_token("s3cr3t"))

        assert result is not None
        assert result.client_id == "stridesync-mcp-client"

    def test_rejects_wrong_token(self):
        verifier = SharedSecretVerifier("s3cr3t")

        assert asyncio.run(verifier.verify_token("wrong")) is None

    def test_rejects_empty_token(self):
        verifier = SharedSecretVerifier("s3cr3t")

        assert asyncio.run(verifier.verify_token("")) is None


class TestCreateServer:
    def test_auth_disabled_by_default(self, tmp_path):
        # mcp_auth_token defaults to "" -- fine for LAN-only setups, but must not silently stay
        # unauthenticated if someone later exposes this port beyond the LAN without setting one.
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)

        mcp = create_server(settings)

        assert mcp.auth is None

    def test_auth_enabled_when_token_configured(self, tmp_path):
        settings = make_settings(tmp_path)
        settings = Settings(**{**settings.__dict__, "mcp_auth_token": "s3cr3t"})
        seed_db(settings.db_path)

        mcp = create_server(settings)

        assert isinstance(mcp.auth, SharedSecretVerifier)

    def test_registers_expected_tools(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        mcp = create_server(settings)

        tools = asyncio.run(mcp.list_tools())
        tool_names = {tool.name for tool in tools}

        assert tool_names == {
            "recent_activities",
            "search_activities",
            "activity_laps",
            "pace_cadence_hr_trend",
            "training_load_summary",
            "training_baseline",
            "activity_hr_zones",
            "activity_samples",
            "last_sync_status",
            "daily_wellness",
            "resting_hr_trend",
            "vo2max_trend",
            "planned_vs_actual",
        }

    def test_tool_reads_from_configured_db(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        mcp = create_server(settings)

        result = asyncio.run(mcp.call_tool("last_sync_status", {}))
        # FastMCP wraps tool results; unwrap to the structured content dict.
        payload = result.structured_content or result.data
        assert payload["status"] == "success"


class TestHttpAuthEnforcement:
    """Confirms bearer-token auth is actually enforced over a real ASGI request/response cycle
    (not just that SharedSecretVerifier's own verify_token logic is correct in isolation) — this
    is the actual boundary protecting personal Garmin data once this port is reachable beyond
    the LAN (see PROJECT_PLAN.md milestone v0.6).
    """

    def _rpc_headers(self, token=None):
        headers = {"Accept": "application/json, text/event-stream"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _mcp_app(self, tmp_path):
        settings = make_settings(tmp_path)
        settings = Settings(**{**settings.__dict__, "mcp_auth_token": "s3cr3t"})
        seed_db(settings.db_path)
        mcp = create_server(settings)
        return mcp.http_app(path="/mcp")

    def test_rejects_request_without_token(self, tmp_path):
        with TestClient(self._mcp_app(tmp_path)) as client:
            response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers=self._rpc_headers(),
            )

        assert response.status_code == 401

    def test_rejects_request_with_wrong_token(self, tmp_path):
        with TestClient(self._mcp_app(tmp_path)) as client:
            response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers=self._rpc_headers("wrong-token"),
            )

        assert response.status_code == 401

    def test_accepts_request_with_correct_token(self, tmp_path):
        with TestClient(self._mcp_app(tmp_path)) as client:
            response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers=self._rpc_headers("s3cr3t"),
            )

        # Not 401: the request got past auth into actual MCP protocol handling (a 400 here is
        # the MCP session-handshake requirement, unrelated to auth — see PR description/commit).
        assert response.status_code != 401
