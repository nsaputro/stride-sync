"""Pydantic schemas and data contracts for StrideSync MCP tools."""

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator


class SingleStep(BaseModel):
    """A single structured workout step with optional duration/distance and pace/HR targets."""

    step_type: Literal["warmup", "interval", "recovery", "cooldown", "rest", "run"] = Field(
        "interval",
        description="Type of workout step: 'warmup', 'interval', 'recovery', 'cooldown', 'rest', or 'run'",
    )
    duration_seconds: Optional[float] = Field(
        None,
        description="Duration of this step in seconds (use either duration_seconds or distance_meters)",
        ge=1.0,
    )
    distance_meters: Optional[float] = Field(
        None,
        description="Distance of this step in meters (use either distance_meters or duration_seconds)",
        ge=1.0,
    )
    target_pace_sec_per_km: Optional[float] = Field(
        None,
        description="Target pace in seconds per kilometer (e.g. 300 for 5:00/km, 240 for 4:00/km)",
        ge=60.0,
    )
    target_pace_min_sec_per_km: Optional[float] = Field(
        None,
        description="Fastest pace bound in sec/km for pace target zone",
        ge=60.0,
    )
    target_pace_max_sec_per_km: Optional[float] = Field(
        None,
        description="Slowest pace bound in sec/km for pace target zone",
        ge=60.0,
    )
    target_hr_low: Optional[int] = Field(
        None,
        description="Lower heart rate target bound in BPM",
        ge=30,
        le=250,
    )
    target_hr_high: Optional[int] = Field(
        None,
        description="Upper heart rate target bound in BPM",
        ge=30,
        le=250,
    )

    @field_validator("step_type", mode="before")
    @classmethod
    def _normalize_step_type(cls, value: Any) -> Any:
        if isinstance(value, str):
            v_low = value.strip().lower()
            if "warm" in v_low:
                return "warmup"
            if "cool" in v_low:
                return "cooldown"
            if "recov" in v_low:
                return "recovery"
            if "rest" in v_low:
                return "rest"
            if "run" in v_low or "inter" in v_low or "tempo" in v_low or "thresh" in v_low:
                return "interval"
            return v_low
        return value or "interval"

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


class RepeatStep(BaseModel):
    """A repeated group of workout steps (e.g. 5x 1km @ 3:50/km with 90s recovery)."""

    step_type: Literal["repeat", "repeat_group", "interval_block"] = Field(
        "repeat",
        description="Block step type, default 'repeat'",
    )
    repeats: int = Field(
        ...,
        description="Number of repetitions/iterations (must be at least 1)",
        ge=1,
    )
    steps: Optional[List[SingleStep]] = Field(
        None,
        description="Ordered list of steps to repeat in each iteration",
    )
    work: Optional[SingleStep] = Field(
        None,
        description="Work interval step (shorthand when steps list is omitted)",
    )
    recovery: Optional[SingleStep] = Field(
        None,
        description="Recovery step between repetitions (shorthand when steps list is omitted)",
    )

    @field_validator("step_type", mode="before")
    @classmethod
    def _normalize_repeat_type(cls, value: Any) -> Any:
        if isinstance(value, str):
            v_low = value.strip().lower()
            if "group" in v_low:
                return "repeat_group"
            if "block" in v_low:
                return "interval_block"
            return "repeat"
        return value

    @field_validator("work", mode="before")
    @classmethod
    def _normalize_work(cls, value: Any) -> Any:
        if isinstance(value, dict) and "step_type" not in value:
            value = dict(value)
            value["step_type"] = "interval"
        return value

    @field_validator("recovery", mode="before")
    @classmethod
    def _normalize_recovery(cls, value: Any) -> Any:
        if isinstance(value, dict) and "step_type" not in value:
            value = dict(value)
            value["step_type"] = "recovery"
        return value

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


WorkoutStep = Union[SingleStep, RepeatStep]


class WorkoutItem(BaseModel):
    """A structured running workout specification to be scheduled on Garmin Connect and recorded locally."""

    workout_date: str = Field(
        ...,
        description="Target workout date in ISO YYYY-MM-DD format (e.g. '2026-10-25')",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    workout_name: str = Field(
        ...,
        description="Descriptive workout title (e.g. '5x1k Threshold Intervals')",
        min_length=1,
    )
    workout_type: str = Field(
        ...,
        description="Workout category (e.g. 'AEROBIC_BASE', 'LACTATE_THRESHOLD', 'RECOVERY', 'LONG_RUN', 'REST')",
        min_length=1,
    )
    reason: str = Field(
        ...,
        description="Coaching rationale for this workout override",
        min_length=1,
    )
    steps: List[WorkoutStep] = Field(
        ...,
        description="Ordered list of structured lap steps and/or repeat blocks",
        min_length=1,
    )
    planned_distance_meters: Optional[float] = Field(
        None,
        description="Total planned distance in meters (auto-computed from steps if omitted)",
        ge=0.0,
    )
    planned_duration_seconds: Optional[float] = Field(
        None,
        description="Total planned duration in seconds (auto-computed from steps if omitted)",
        ge=0.0,
    )
    planned_target_pace_sec_per_km: Optional[float] = Field(
        None,
        description="Overall target pace in seconds per kilometer override",
        ge=60.0,
    )
    planned_target_hr_low: Optional[int] = Field(
        None,
        description="Overall lower heart rate target bound in BPM",
        ge=30,
        le=250,
    )
    planned_target_hr_high: Optional[int] = Field(
        None,
        description="Overall upper heart rate target bound in BPM",
        ge=30,
        le=250,
    )
    notes: Optional[str] = Field(
        None,
        description="Optional execution notes or coaching cues",
    )

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


class ScheduledWorkoutResult(BaseModel):
    """Result summary of a scheduled workout override."""

    workout_date: str = Field(..., description="Target workout date (YYYY-MM-DD)")
    workout_name: str = Field(..., description="Name of the scheduled workout")
    workout_type: str = Field(..., description="Workout category")
    reason: str = Field(..., description="Coaching rationale")
    garmin_workout_id: Optional[int] = Field(None, description="Garmin Connect workout template ID")
    garmin_schedule_id: Optional[int] = Field(None, description="Garmin Connect calendar schedule ID")
    planned_distance_meters: Optional[float] = Field(None, description="Planned distance in meters")
    planned_duration_seconds: Optional[float] = Field(None, description="Planned duration in seconds")
    planned_target_pace_sec_per_km: Optional[float] = Field(None, description="Target pace in sec/km")
    planned_target_hr_low: Optional[int] = Field(None, description="Target heart rate low")
    planned_target_hr_high: Optional[int] = Field(None, description="Target heart rate high")
    notes: Optional[str] = Field(None, description="Execution notes")
    steps: Optional[List[Dict[str, Any]]] = Field(None, description="Structured steps as scheduled")

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


class DeleteOverrideResult(BaseModel):
    """Result of deleting a plan override."""

    status: str = Field("deleted", description="Outcome status")
    workout_date: str = Field(..., description="Deleted override date")

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


class GearActionResult(BaseModel):
    """Result of assigning or unassigning activity gear."""

    status: str = Field(..., description="Outcome status ('added' or 'removed')")
    activity_id: int = Field(..., description="Activity ID")
    gear_uuid: str = Field(..., description="Gear UUID")

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)
