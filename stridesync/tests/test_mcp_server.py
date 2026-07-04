import asyncio
import sqlite3

import pytest

from app import db
from app.mcp.server import (
    _clamp,
    _connect_readonly,
    create_server,
    get_activity_laps,
    get_last_sync_status,
    get_pace_cadence_hr_trend,
    get_training_load_summary,
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


class TestCreateServer:
    def test_registers_expected_tools(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        mcp = create_server(settings)

        tools = asyncio.run(mcp.list_tools())
        tool_names = {tool.name for tool in tools}

        assert tool_names == {
            "recent_activities",
            "activity_laps",
            "pace_cadence_hr_trend",
            "training_load_summary",
            "last_sync_status",
        }

    def test_tool_reads_from_configured_db(self, tmp_path):
        settings = make_settings(tmp_path)
        seed_db(settings.db_path)
        mcp = create_server(settings)

        result = asyncio.run(mcp.call_tool("last_sync_status", {}))
        # FastMCP wraps tool results; unwrap to the structured content dict.
        payload = result.structured_content or result.data
        assert payload["status"] == "success"
