"""Tests for Pydantic schemas in app.mcp.schemas."""

import pytest
from pydantic import ValidationError

from app.mcp.schemas import (
    DeleteOverrideResult,
    GearActionResult,
    RepeatStep,
    ScheduledWorkoutResult,
    SingleStep,
    WorkoutItem,
)


class TestSingleStepSchema:
    def test_valid_single_step_defaults(self):
        step = SingleStep(duration_seconds=300)
        assert step.step_type == "interval"
        assert step.duration_seconds == 300.0
        assert step.distance_meters is None
        assert step["step_type"] == "interval"

    def test_single_step_normalization(self):
        warmup = SingleStep(step_type="WARMUP", distance_meters=2000)
        assert warmup.step_type == "warmup"

        cooldown = SingleStep(step_type="cooldown_run", distance_meters=1000)
        assert cooldown.step_type == "cooldown"

        recovery = SingleStep(step_type="recovery_jog", duration_seconds=90)
        assert recovery.step_type == "recovery"

        rest = SingleStep(step_type="Rest", duration_seconds=60)
        assert rest.step_type == "rest"

        tempo = SingleStep(step_type="tempo_run", distance_meters=5000)
        assert tempo.step_type == "interval"

    def test_single_step_targets(self):
        step = SingleStep(
            step_type="interval",
            distance_meters=1000,
            target_pace_sec_per_km=240,
            target_pace_min_sec_per_km=235,
            target_pace_max_sec_per_km=245,
            target_hr_low=160,
            target_hr_high=175,
        )
        assert step.target_pace_sec_per_km == 240.0
        assert step.target_hr_low == 160
        assert step.target_hr_high == 175


class TestRepeatStepSchema:
    def test_repeat_step_with_nested_steps(self):
        rep = RepeatStep(
            repeats=5,
            steps=[
                SingleStep(step_type="interval", distance_meters=1000, target_pace_sec_per_km=230),
                SingleStep(step_type="recovery", duration_seconds=90),
            ],
        )
        assert rep.step_type == "repeat"
        assert rep.repeats == 5
        assert len(rep.steps) == 2
        assert rep["repeats"] == 5

    def test_repeat_step_with_work_and_recovery_shorthand(self):
        rep = RepeatStep(
            repeats=6,
            work={"distance_meters": 800},
            recovery={"duration_seconds": 60},
        )
        assert rep.work.step_type == "interval"
        assert rep.work.distance_meters == 800.0
        assert rep.recovery.step_type == "recovery"
        assert rep.recovery.duration_seconds == 60.0

    def test_repeat_step_requires_positive_repeats(self):
        with pytest.raises(ValidationError):
            RepeatStep(repeats=0)


class TestWorkoutItemSchema:
    def test_valid_workout_item(self):
        item = WorkoutItem(
            workout_date="2026-10-25",
            workout_name="Sunday Long Run",
            workout_type="AEROBIC_BASE",
            reason="Aerobic endurance base",
            steps=[
                {"step_type": "warmup", "duration_seconds": 600},
                {"step_type": "interval", "distance_meters": 15000, "target_pace_sec_per_km": 320},
                {"step_type": "cooldown", "duration_seconds": 600},
            ],
        )
        assert item.workout_date == "2026-10-25"
        assert len(item.steps) == 3
        assert isinstance(item.steps[0], SingleStep)
        assert item["workout_name"] == "Sunday Long Run"

    def test_invalid_date_format_fails(self):
        with pytest.raises(ValidationError):
            WorkoutItem(
                workout_date="25-10-2026",
                workout_name="Run",
                workout_type="BASE",
                reason="Base",
                steps=[{"duration_seconds": 600}],
            )


class TestResultSchemas:
    def test_scheduled_workout_result_indexing(self):
        res = ScheduledWorkoutResult(
            workout_date="2026-10-25",
            workout_name="Long Run",
            workout_type="AEROBIC_BASE",
            reason="Endurance",
            garmin_workout_id=123,
            garmin_schedule_id=456,
        )
        assert res.workout_date == "2026-10-25"
        assert res["workout_date"] == "2026-10-25"
        assert res["garmin_workout_id"] == 123

    def test_delete_override_result(self):
        res = DeleteOverrideResult(workout_date="2026-10-25")
        assert res.status == "deleted"
        assert res["workout_date"] == "2026-10-25"

    def test_gear_action_result(self):
        res = GearActionResult(status="added", activity_id=99, gear_uuid="uuid-1")
        assert res.status == "added"
        assert res["activity_id"] == 99
