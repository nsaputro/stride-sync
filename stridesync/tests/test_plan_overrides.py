import asyncio
from datetime import datetime, timezone
import pytest

from app import db
from app.config import Settings
from app.mcp.server import (
    create_server,
    delete_plan_override,
    get_plan_overrides,
    get_planned_vs_actual,
    set_plan_override,
)


def make_settings(tmp_path) -> Settings:
    return Settings(
        garmin_username="user@example.com",
        garmin_password="password",
        sync_interval_hours=6,
        mcp_port=8765,
        log_level="info",
        db_path=str(tmp_path / "stridesync.db"),
        garmin_token_dir=str(tmp_path / "garmin_tokens"),
        mfa_web_port=8767,
    )


class TestPlanOverrideCRUD:
    def test_set_plan_override_new_record(self, tmp_path):
        settings = make_settings(tmp_path)
        conn = db.connect(settings.db_path)
        try:
            record = set_plan_override(
                conn,
                workout_date="2026-10-05",
                workout_name="Taper Long Run + Marathon Pace",
                workout_type="AEROBIC_BASE",
                reason="Taper week 1: reduce eccentric fatigue from 30k Almere",
                planned_distance_meters=18000.0,
                planned_duration_seconds=5400.0,
                planned_target_pace_sec_per_km=300.0,
                planned_target_hr_low=135,
                planned_target_hr_high=150,
                notes="Take 2 gels with sodium; keep HR below 150 bpm",
            )
            assert record["workout_date"] == "2026-10-05"
            assert record["workout_name"] == "Taper Long Run + Marathon Pace"
            assert record["workout_type"] == "AEROBIC_BASE"
            assert record["reason"] == "Taper week 1: reduce eccentric fatigue from 30k Almere"
            assert record["planned_distance_meters"] == 18000.0
            assert record["planned_duration_seconds"] == 5400.0
            assert record["planned_target_pace_sec_per_km"] == 300.0
            assert record["planned_target_hr_low"] == 135
            assert record["planned_target_hr_high"] == 150
            assert record["notes"] == "Take 2 gels with sodium; keep HR below 150 bpm"
            assert "created_at" in record and record["created_at"]
            assert "updated_at" in record and record["updated_at"]
        finally:
            conn.close()

    def test_set_plan_override_update_preserves_created_at(self, tmp_path):
        settings = make_settings(tmp_path)
        conn = db.connect(settings.db_path)
        try:
            initial = set_plan_override(
                conn,
                workout_date="2026-10-05",
                workout_name="Initial Workout",
                workout_type="AEROBIC_BASE",
                reason="Initial reason",
            )
            created_at = initial["created_at"]

            updated = set_plan_override(
                conn,
                workout_date="2026-10-05",
                workout_name="Updated Workout",
                workout_type="LACTATE_THRESHOLD",
                reason="Updated reason for change",
                notes="New instructions",
            )
            assert updated["workout_name"] == "Updated Workout"
            assert updated["workout_type"] == "LACTATE_THRESHOLD"
            assert updated["reason"] == "Updated reason for change"
            assert updated["notes"] == "New instructions"
            assert updated["created_at"] == created_at
        finally:
            conn.close()

    def test_set_plan_override_validation_errors(self, tmp_path):
        settings = make_settings(tmp_path)
        conn = db.connect(settings.db_path)
        try:
            with pytest.raises(ValueError, match="workout_date"):
                set_plan_override(
                    conn,
                    workout_date="not-a-date",
                    workout_name="Run",
                    workout_type="BASE",
                    reason="Reason",
                )

            with pytest.raises(ValueError, match="workout_name"):
                set_plan_override(
                    conn,
                    workout_date="2026-10-05",
                    workout_name="",
                    workout_type="BASE",
                    reason="Reason",
                )

            with pytest.raises(ValueError, match="workout_type"):
                set_plan_override(
                    conn,
                    workout_date="2026-10-05",
                    workout_name="Run",
                    workout_type="",
                    reason="Reason",
                )

            with pytest.raises(ValueError, match="reason"):
                set_plan_override(
                    conn,
                    workout_date="2026-10-05",
                    workout_name="Run",
                    workout_type="BASE",
                    reason="   ",
                )
        finally:
            conn.close()

    def test_get_plan_overrides_filtering(self, tmp_path):
        settings = make_settings(tmp_path)
        conn = db.connect(settings.db_path)
        try:
            set_plan_override(conn, "2026-10-01", "Day 1", "BASE", "Reason 1")
            set_plan_override(conn, "2026-10-05", "Day 5", "TEMPO", "Reason 5")
            set_plan_override(conn, "2026-10-10", "Day 10", "REST", "Reason 10")

            all_records = get_plan_overrides(conn, start_date="2026-10-01", end_date="2026-10-10")
            assert len(all_records) == 3
            assert [r["workout_date"] for r in all_records] == [
                "2026-10-01",
                "2026-10-05",
                "2026-10-10",
            ]

            subset = get_plan_overrides(conn, start_date="2026-10-02", end_date="2026-10-06")
            assert len(subset) == 1
            assert subset[0]["workout_date"] == "2026-10-05"

            after = get_plan_overrides(conn, start_date="2026-10-05")
            assert len(after) == 2
            assert [r["workout_date"] for r in after] == ["2026-10-05", "2026-10-10"]

            before = get_plan_overrides(conn, end_date="2026-10-04")
            assert len(before) == 1
            assert before[0]["workout_date"] == "2026-10-01"

            with pytest.raises(ValueError, match="start_date"):
                get_plan_overrides(conn, start_date="bad-date")

            with pytest.raises(ValueError, match="end_date"):
                get_plan_overrides(conn, end_date="bad-date")
        finally:
            conn.close()

    def test_delete_plan_override(self, tmp_path):
        settings = make_settings(tmp_path)
        conn = db.connect(settings.db_path)
        try:
            set_plan_override(conn, "2026-10-05", "Run", "BASE", "Reason")
            assert len(get_plan_overrides(conn, start_date="2026-10-01", end_date="2026-10-10")) == 1

            result = delete_plan_override(conn, "2026-10-05")
            assert result == {"status": "deleted", "workout_date": "2026-10-05"}

            assert len(get_plan_overrides(conn, start_date="2026-10-01", end_date="2026-10-10")) == 0

            with pytest.raises(ValueError, match="No plan override found"):
                delete_plan_override(conn, "2026-10-05")

            with pytest.raises(ValueError, match="workout_date"):
                delete_plan_override(conn, "invalid")
        finally:
            conn.close()


class TestPlannedVsActualMerging:
    def test_planned_vs_actual_merges_overrides_and_preserves_originals(self, tmp_path):
        settings = make_settings(tmp_path)
        conn = db.connect(settings.db_path)
        try:
            # 1. Garmin planned workout on 2026-07-10 (not overridden)
            conn.execute(
                """
                INSERT INTO planned_workouts (
                    plan_id, workout_date, workout_name, workout_type,
                    planned_distance_meters, planned_duration_seconds,
                    planned_target_pace_sec_per_km, planned_target_hr_low, planned_target_hr_high,
                    synced_at
                ) VALUES (
                    'plan-1', '2026-07-10', 'Garmin Base Run', 'AEROBIC_BASE',
                    6000, 2000, 333.3, 130, 145, '2026-07-09T00:00:00+00:00'
                )
                """
            )
            # Logged activity matching 2026-07-10
            conn.execute(
                """
                INSERT INTO activities (
                    activity_id, activity_name, activity_type, start_time_local,
                    duration_seconds, distance_meters, average_pace_sec_per_km, average_hr,
                    synced_at
                ) VALUES (
                    101, 'Friday Base Run', 'running', '2026-07-10 07:00:00',
                    1950, 6100, 320.0, 138, '2026-07-10T08:00:00+00:00'
                )
                """
            )

            # 2. Garmin planned workout on 2026-07-11 (overridden)
            conn.execute(
                """
                INSERT INTO planned_workouts (
                    plan_id, workout_date, workout_name, workout_type,
                    planned_distance_meters, planned_duration_seconds,
                    planned_target_pace_sec_per_km, planned_target_hr_low, planned_target_hr_high,
                    synced_at
                ) VALUES (
                    'plan-1', '2026-07-11', 'Garmin Sprints', 'ANAEROBIC_SPRINT',
                    5000, 1800, 300.0, 150, 175, '2026-07-09T00:00:00+00:00'
                )
                """
            )
            set_plan_override(
                conn,
                workout_date="2026-07-11",
                workout_name="Overridden Easy Aerobic",
                workout_type="AEROBIC_BASE",
                reason="Calf tightness after speed work; substitute easy aerobic base",
                planned_distance_meters=7000.0,
                planned_duration_seconds=2400.0,
                planned_target_pace_sec_per_km=340.0,
                planned_target_hr_low=125,
                planned_target_hr_high=140,
                notes="Keep cadence high and effort relaxed",
            )

            # 3. Plan override on 2026-07-12 without an existing Garmin workout
            set_plan_override(
                conn,
                workout_date="2026-07-12",
                workout_name="Bonus Recovery Shakeout",
                workout_type="RECOVERY",
                reason="Leg loosen up before next week's long run",
                planned_distance_meters=4000.0,
                planned_duration_seconds=1500.0,
                notes="Grass surface preferred",
            )

            # Query planned_vs_actual with a large window that covers these dates
            rows = get_planned_vs_actual(conn, days=365)
            # Filter specifically to our test dates
            test_rows = [r for r in rows if r["workout_date"] in ("2026-07-10", "2026-07-11", "2026-07-12")]
            assert len(test_rows) == 3

            # Row 1: Not overridden
            r1 = test_rows[0]
            assert r1["workout_date"] == "2026-07-10"
            assert r1["is_overridden"] is False
            assert r1["workout_name"] == "Garmin Base Run"
            assert r1["workout_type"] == "AEROBIC_BASE"
            assert r1["planned_distance_meters"] == 6000.0
            assert r1["override_reason"] is None
            assert r1["override_notes"] is None
            assert r1["garmin_planned_workout_name"] == "Garmin Base Run"
            assert r1["garmin_planned_distance_meters"] == 6000.0
            assert r1["activity_id"] == 101
            assert r1["actual_distance_meters"] == 6100.0

            # Row 2: Overridden
            r2 = test_rows[1]
            assert r2["workout_date"] == "2026-07-11"
            assert r2["is_overridden"] is True
            assert r2["workout_name"] == "Overridden Easy Aerobic"
            assert r2["workout_type"] == "AEROBIC_BASE"
            assert r2["planned_distance_meters"] == 7000.0
            assert r2["planned_duration_seconds"] == 2400.0
            assert r2["override_reason"] == "Calf tightness after speed work; substitute easy aerobic base"
            assert r2["override_notes"] == "Keep cadence high and effort relaxed"
            # Original Garmin values preserved
            assert r2["garmin_planned_workout_name"] == "Garmin Sprints"
            assert r2["garmin_planned_workout_type"] == "ANAEROBIC_SPRINT"
            assert r2["garmin_planned_distance_meters"] == 5000.0
            assert r2["garmin_planned_duration_seconds"] == 1800.0

            # Row 3: Override only (no Garmin plan)
            r3 = test_rows[2]
            assert r3["workout_date"] == "2026-07-12"
            assert r3["is_overridden"] is True
            assert r3["workout_name"] == "Bonus Recovery Shakeout"
            assert r3["workout_type"] == "RECOVERY"
            assert r3["planned_distance_meters"] == 4000.0
            assert r3["override_reason"] == "Leg loosen up before next week's long run"
            assert r3["override_notes"] == "Grass surface preferred"
            assert r3["garmin_planned_workout_name"] is None
            assert r3["garmin_planned_distance_meters"] is None

            # 4. Deleting the override reverts Row 2 to Garmin default
            delete_plan_override(conn, "2026-07-11")
            after_delete = [r for r in get_planned_vs_actual(conn, days=365) if r["workout_date"] == "2026-07-11"]
            assert len(after_delete) == 1
            assert after_delete[0]["is_overridden"] is False
            assert after_delete[0]["workout_name"] == "Garmin Sprints"
            assert after_delete[0]["override_reason"] is None
        finally:
            conn.close()


class TestFastMCPPlanOverrideTools:
    def test_mcp_tools_invoke_successfully(self, tmp_path):
        settings = make_settings(tmp_path)
        conn = db.connect(settings.db_path)
        conn.close()

        server = create_server(settings)

        # 1. set_plan_override
        res_set = asyncio.run(
            server.call_tool(
                "set_plan_override",
                {
                    "workout_date": "2026-10-15",
                    "workout_name": "Threshold Intervals 4x2km",
                    "workout_type": "LACTATE_THRESHOLD",
                    "reason": "Marathon specific pace block substitution",
                    "planned_distance_meters": 12000.0,
                    "planned_duration_seconds": 3600.0,
                },
            )
        )
        set_data = res_set.structured_content or res_set.data
        assert set_data["workout_date"] == "2026-10-15"
        assert set_data["workout_name"] == "Threshold Intervals 4x2km"
        assert set_data["reason"] == "Marathon specific pace block substitution"

        # 2. get_plan_overrides
        res_get = asyncio.run(
            server.call_tool(
                "get_plan_overrides",
                {
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-31",
                },
            )
        )
        get_data = (
            res_get.structured_content.get("result", res_get.structured_content)
            if isinstance(res_get.structured_content, dict)
            else (res_get.structured_content or res_get.data)
        )
        assert len(get_data) == 1
        assert get_data[0]["workout_date"] == "2026-10-15"

        # 3. planned_vs_actual
        res_pva = asyncio.run(server.call_tool("planned_vs_actual", {"days": 365}))
        pva_data = (
            res_pva.structured_content.get("result", res_pva.structured_content)
            if isinstance(res_pva.structured_content, dict)
            else (res_pva.structured_content or res_pva.data)
        )
        match = next(r for r in pva_data if r["workout_date"] == "2026-10-15")
        assert match["is_overridden"] is True
        assert match["workout_name"] == "Threshold Intervals 4x2km"
        assert match["override_reason"] == "Marathon specific pace block substitution"

        # 4. delete_plan_override
        res_del = asyncio.run(server.call_tool("delete_plan_override", {"workout_date": "2026-10-15"}))
        del_data = res_del.structured_content or res_del.data
        assert del_data == {"status": "deleted", "workout_date": "2026-10-15"}

        # Verify deletion
        res_after = asyncio.run(
            server.call_tool(
                "get_plan_overrides",
                {
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-31",
                },
            )
        )
        after_data = (
            res_after.structured_content.get("result", res_after.structured_content)
            if isinstance(res_after.structured_content, dict)
            else (res_after.structured_content or res_after.data)
        )
        assert after_data == []

