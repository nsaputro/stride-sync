import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import requests
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from app.sync.garmin_client import (
    GarminAPIError,
    GarminAuthError,
    GarminClient,
    _normalize_activity,
    _normalize_daily_wellness,
    _normalize_hr_zones,
    _normalize_lap,
    _normalize_planned_workouts,
    _normalize_samples,
    _normalize_training_baseline,
    _normalize_vo2max,
    _pace_sec_per_km,
    describe_transport_error,
)


def make_list_item(**overrides):
    defaults = dict(
        activityId=123,
        activityName="Morning Run",
        startTimeLocal="2026-06-01 06:30:00",
        startTimeGMT="2026-06-01 13:30:00",
        activityType={"typeKey": "running"},
        duration=1800.0,
        movingDuration=1750.0,
        averageHR=150,
        maxHR=172,
        aerobicTrainingEffect=3.2,
        anaerobicTrainingEffect=0.5,
        trainingEffectLabel="TEMPO",
        activityTrainingLoad=85.0,
    )
    defaults.update(overrides)
    return defaults


class TestPaceConversion:
    def test_positive_speed(self):
        assert _pace_sec_per_km(2.5) == pytest.approx(400.0)

    def test_zero_speed_is_none(self):
        assert _pace_sec_per_km(0) is None

    def test_missing_speed_is_none(self):
        assert _pace_sec_per_km(None) is None


class TestNormalizeActivity:
    def test_merges_list_item_and_detail(self):
        list_item = make_list_item()
        detail = {
            "summaryDTO": {
                "distance": 5000.0,
                "averageSpeed": 2.78,
                "averageHR": 151,
                "maxHR": 173,
                "averageRunningCadenceInStepsPerMinute": 170.0,
                "maxRunningCadenceInStepsPerMinute": 182.0,
                "elevationGain": 45.0,
                "elevationLoss": 40.0,
                "calories": 320.0,
            }
        }

        activity = _normalize_activity(list_item, detail)

        assert activity.activity_id == 123
        assert activity.activity_type == "running"
        assert activity.distance_meters == 5000.0
        assert activity.average_speed_mps == 2.78
        assert activity.average_pace_sec_per_km == pytest.approx(1000.0 / 2.78)
        assert activity.average_cadence_spm == 170.0
        assert activity.max_cadence_spm == 182.0
        assert activity.elevation_gain_meters == 45.0
        assert activity.calories == 320.0
        # List-only fields still come through
        assert activity.average_hr == 150
        assert activity.activity_training_load == 85.0

    def test_missing_detail_does_not_crash(self):
        list_item = make_list_item()
        activity = _normalize_activity(list_item, {})

        assert activity.activity_id == 123
        assert activity.distance_meters is None
        assert activity.average_pace_sec_per_km is None


class TestNormalizeLap:
    def test_normalizes_raw_lap_dict(self):
        raw = {
            "startTimeGMT": "2026-06-01 13:30:00",
            "duration": 300.0,
            "distance": 1000.0,
            "averageSpeed": 3.0,
            "averageHR": 148,
            "maxHR": 160,
            "averageRunCadence": 172.0,
            "maxRunCadence": 178.0,
        }

        lap = _normalize_lap(activity_id=123, lap_index=0, raw=raw)

        assert lap.activity_id == 123
        assert lap.lap_index == 0
        assert lap.distance_meters == 1000.0
        assert lap.pace_sec_per_km == pytest.approx(1000.0 / 3.0)
        assert lap.average_cadence_spm == 172.0


class TestNormalizeTrainingBaseline:
    def test_merges_threshold_and_predictions(self):
        threshold = {
            "speed_and_heart_rate": {"speed": 3.2, "heartRate": 165},
        }
        predictions = {
            "raceTime5K": 1200,
            "raceTime10K": 2500,
            "raceTimeHalfMarathon": 5600,
            "raceTimeMarathon": 11800,
        }

        baseline = _normalize_training_baseline(threshold, predictions)

        assert baseline.lactate_threshold_hr == 165
        assert baseline.lactate_threshold_speed_mps == 3.2
        assert baseline.lactate_threshold_pace_sec_per_km == pytest.approx(1000.0 / 3.2)
        assert baseline.race_prediction_5k_seconds == 1200
        assert baseline.race_prediction_10k_seconds == 2500
        assert baseline.race_prediction_half_marathon_seconds == 5600
        assert baseline.race_prediction_marathon_seconds == 11800

    def test_missing_data_does_not_crash(self):
        baseline = _normalize_training_baseline({}, {})

        assert baseline.lactate_threshold_hr is None
        assert baseline.race_prediction_marathon_seconds is None


class TestNormalizeDailyWellness:
    def test_merges_all_five_sources(self):
        sleep = {
            "dailySleepDTO": {
                "sleepTimeSeconds": 27000.0,
                "deepSleepSeconds": 5400.0,
                "lightSleepSeconds": 14400.0,
                "remSleepSeconds": 6300.0,
                "awakeSleepSeconds": 900.0,
                "sleepScores": {"overall": {"value": 82}},
            }
        }
        hrv = {
            "hrvSummary": {
                "status": "BALANCED",
                "weeklyAvg": 55.0,
                "lastNightAvg": 53.0,
            }
        }
        training_status = {"latestTrainingStatus": "PRODUCTIVE"}
        readiness = {"score": 78}
        resting_hr = {"restingHeartRate": 48}

        wellness = _normalize_daily_wellness(
            "2026-07-06", sleep, hrv, training_status, readiness, resting_hr
        )

        assert wellness.calendar_date == "2026-07-06"
        assert wellness.sleep_score == 82
        assert wellness.sleep_duration_seconds == 27000.0
        assert wellness.deep_sleep_seconds == 5400.0
        assert wellness.light_sleep_seconds == 14400.0
        assert wellness.rem_sleep_seconds == 6300.0
        assert wellness.awake_sleep_seconds == 900.0
        assert wellness.hrv_status == "BALANCED"
        assert wellness.hrv_weekly_avg_ms == 55.0
        assert wellness.hrv_last_night_avg_ms == 53.0
        assert wellness.training_status_label == "PRODUCTIVE"
        assert wellness.training_readiness_score == 78
        assert wellness.resting_hr == 48

    def test_unwraps_nested_training_status_dict(self):
        training_status = {
            "latestTrainingStatus": {"trainingStatusFeedbackPhrase": "OVERREACHING"}
        }

        wellness = _normalize_daily_wellness("2026-07-06", {}, {}, training_status, {}, {})

        assert wellness.training_status_label == "OVERREACHING"

    def test_missing_data_does_not_crash(self):
        wellness = _normalize_daily_wellness("2026-07-06", {}, {}, {}, {}, {})

        assert wellness.calendar_date == "2026-07-06"
        assert wellness.sleep_score is None
        assert wellness.hrv_status is None
        assert wellness.training_status_label is None
        assert wellness.training_readiness_score is None
        assert wellness.resting_hr is None


class TestNormalizeVo2Max:
    def test_merges_running_and_cycling(self):
        raw = {
            "generic": {"vo2MaxPreciseValue": 52.5},
            "cycling": {"vo2MaxPreciseValue": 48.0},
            "fitnessAge": 28,
        }

        reading = _normalize_vo2max("2026-07-06", raw)

        assert reading.calendar_date == "2026-07-06"
        assert reading.vo2_max_running == 52.5
        assert reading.vo2_max_cycling == 48.0
        assert reading.fitness_age == 28

    def test_missing_data_does_not_crash(self):
        reading = _normalize_vo2max("2026-07-06", {})

        assert reading.calendar_date == "2026-07-06"
        assert reading.vo2_max_running is None
        assert reading.vo2_max_cycling is None
        assert reading.fitness_age is None

    def test_unwraps_the_real_list_wrapped_response(self):
        # Regression test: get_max_metrics' real successful response is a *list* containing one
        # dict, not a bare dict -- a prior guard treated any list as "no data" and silently
        # discarded every real response (rows still got inserted via calendar_date, but every
        # numeric field came back NULL). Values below match a real account's pasted diagnostic
        # output byte-for-byte (see PROJECT_PLAN.md milestone Stage 12 follow-up).
        raw = [
            {
                "userId": 86560492,
                "generic": {
                    "calendarDate": "2026-07-07",
                    "vo2MaxPreciseValue": 55.2,
                    "vo2MaxValue": 55.0,
                    "fitnessAge": None,
                    "fitnessAgeDescription": None,
                    "maxMetCategory": 0,
                },
                "cycling": None,
                "heatAltitudeAcclimation": {"calendarDate": "2026-07-07"},
            }
        ]

        reading = _normalize_vo2max("2026-07-06", raw)

        assert reading.calendar_date == "2026-07-06"
        assert reading.vo2_max_running == 55.2
        assert reading.vo2_max_cycling is None
        assert reading.fitness_age is None

    def test_list_with_no_dict_element_does_not_crash(self):
        reading = _normalize_vo2max("2026-07-06", ["not-a-dict", 42])

        assert reading.calendar_date == "2026-07-06"
        assert reading.vo2_max_running is None
        assert reading.vo2_max_cycling is None
        assert reading.fitness_age is None

    def test_fitness_age_nested_under_generic_takes_priority_over_top_level(self):
        raw = {"generic": {"fitnessAge": 28}, "fitnessAge": 99}

        reading = _normalize_vo2max("2026-07-06", raw)

        assert reading.fitness_age == 28


def make_task_entry(
    calendar_date="2026-07-07",
    workout_name="Threshold",
    training_effect_label="LACTATE_THRESHOLD",
    duration_secs=3660,
    rest_day=False,
):
    """Build one `taskList` entry matching the real `get_adaptive_training_plan_by_id` shape
    (see `_normalize_planned_workouts`'s docstring) -- confirmed live, not a guess.
    """
    if rest_day:
        task_workout = {
            "workoutId": None,
            "sportType": None,
            "workoutName": None,
            "workoutDescription": None,
            "scheduledDate": f"{calendar_date}T00:25:36.0",
            "restDay": True,
        }
    else:
        task_workout = {
            "workoutId": None,
            "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
            "workoutName": workout_name,
            "workoutDescription": "2x18:00@162bpm",
            "scheduledDate": f"{calendar_date}T00:25:36.0",
            "estimatedDurationInSecs": duration_secs,
            "trainingEffectLabel": training_effect_label,
            "restDay": False,
        }
    return {
        "trainingPlanId": 43075722,
        "weekId": 33,
        "dayOfWeekId": 2,
        "taskWorkout": task_workout,
        "calendarDate": calendar_date,
    }


class TestNormalizePlannedWorkouts:
    def test_normalizes_one_in_window_workout(self):
        # Real shape confirmed live against an FBT_ADAPTIVE plan -- estimatedDurationInSecs=3120
        # matched that account's Garmin Connect app showing "52:00" for the same workout.
        detail = {
            "taskList": [
                make_task_entry(
                    calendar_date="2026-07-10",
                    workout_name="Base",
                    training_effect_label="AEROBIC_BASE",
                    duration_secs=3120,
                )
            ]
        }

        workouts = _normalize_planned_workouts("43075722", detail, "2026-07-01", "2026-07-10")

        assert len(workouts) == 1
        w = workouts[0]
        assert w.plan_id == "43075722"
        assert w.workout_date == "2026-07-10"
        assert w.workout_name == "Base"
        assert w.workout_type == "AEROBIC_BASE"
        assert w.planned_duration_seconds == 3120
        # No structured target field exists in the real response -- always None for now.
        assert w.planned_distance_meters is None
        assert w.planned_target_pace_sec_per_km is None
        assert w.planned_target_hr_low is None
        assert w.planned_target_hr_high is None

    def test_skips_rest_days(self):
        # A day entry whose taskWorkout.restDay is true has no real workout (workoutName/
        # sportType are null) -- must not produce an empty placeholder row.
        detail = {
            "taskList": [
                make_task_entry(calendar_date="2026-07-08", rest_day=True),
                make_task_entry(calendar_date="2026-07-09", workout_name="Base"),
            ]
        }

        workouts = _normalize_planned_workouts("43075722", detail, "2026-07-01", "2026-07-10")

        assert len(workouts) == 1
        assert workouts[0].workout_date == "2026-07-09"

    def test_filters_out_workout_outside_window(self):
        detail = {"taskList": [make_task_entry(calendar_date="2026-08-01")]}

        workouts = _normalize_planned_workouts("plan-1", detail, "2026-07-01", "2026-07-10")

        assert workouts == []

    def test_missing_task_list_key_returns_empty(self):
        assert _normalize_planned_workouts("plan-1", {}, "2026-07-01", "2026-07-10") == []

    def test_entry_missing_date_is_skipped(self):
        detail = {"taskList": [{"taskWorkout": {"workoutName": "No Date Run"}}]}

        assert _normalize_planned_workouts("plan-1", detail, "2026-07-01", "2026-07-10") == []

    def test_falls_back_to_legacy_workouts_key(self):
        # Kept as a lower-priority fallback in case a non-adaptive (phased) plan's shape
        # differs from the confirmed FBT_ADAPTIVE taskList shape.
        detail = {"workouts": [{"date": "2026-07-06", "taskWorkout": {"workoutName": "Tempo"}}]}

        workouts = _normalize_planned_workouts("plan-1", detail, "2026-07-01", "2026-07-10")

        assert len(workouts) == 1
        assert workouts[0].workout_name == "Tempo"

    def test_normalizes_the_exact_real_response_reported_live(self):
        # Trimmed but structurally faithful copy of the actual get_adaptive_training_plan_by_id
        # response a live user pasted back via the Diagnostics panel -- the durations below
        # (3660/3120/3000 secs) were independently confirmed to match "1:01:00"/"52:00"/"50:00"
        # shown in that account's own Garmin Connect app for the same workouts.
        detail = {
            "trainingPlanId": 43075722,
            "trainingPlanCategory": "FBT_ADAPTIVE",
            "name": "TCS Amsterdam Marathon Plan",
            "taskList": [
                {
                    "trainingPlanId": 43075722,
                    "taskWorkout": {
                        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
                        "workoutName": "Threshold",
                        "workoutDescription": "2x18:00@162bpm",
                        "estimatedDurationInSecs": 3660,
                        "trainingEffectLabel": "LACTATE_THRESHOLD",
                        "restDay": False,
                    },
                    "calendarDate": "2026-07-07",
                },
                {
                    "trainingPlanId": 43075722,
                    "taskWorkout": {
                        "sportType": None,
                        "workoutName": None,
                        "workoutDescription": None,
                        "trainingEffectLabel": "INVALID",
                        "restDay": True,
                    },
                    "calendarDate": "2026-07-08",
                },
                {
                    "trainingPlanId": 43075722,
                    "taskWorkout": {
                        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
                        "workoutName": "Base",
                        "workoutDescription": "137bpm",
                        "estimatedDurationInSecs": 5100,
                        "trainingEffectLabel": "AEROBIC_BASE",
                        "restDay": False,
                    },
                    "calendarDate": "2026-07-09",
                },
                {
                    "trainingPlanId": 43075722,
                    "taskWorkout": {
                        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
                        "workoutName": "Base",
                        "workoutDescription": "137bpm",
                        "estimatedDurationInSecs": 3120,
                        "trainingEffectLabel": "AEROBIC_BASE",
                        "restDay": False,
                    },
                    "calendarDate": "2026-07-10",
                },
                {
                    "trainingPlanId": 43075722,
                    "taskWorkout": {
                        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
                        "workoutName": "Anaerobic",
                        "workoutDescription": "7x1:00@Very Hard",
                        "estimatedDurationInSecs": 3000,
                        "trainingEffectLabel": "ANAEROBIC_CAPACITY",
                        "restDay": False,
                    },
                    "calendarDate": "2026-07-11",
                },
                {
                    "trainingPlanId": 43075722,
                    "taskWorkout": {
                        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
                        "workoutName": "Base",
                        "workoutDescription": "137bpm",
                        "estimatedDurationInSecs": 3480,
                        "trainingEffectLabel": "AEROBIC_BASE",
                        "restDay": False,
                    },
                    "calendarDate": "2026-07-12",
                },
                {
                    "trainingPlanId": 43075722,
                    "taskWorkout": {
                        "sportType": None,
                        "workoutName": None,
                        "workoutDescription": None,
                        "trainingEffectLabel": "INVALID",
                        "restDay": True,
                    },
                    "calendarDate": "2026-07-13",
                },
            ],
            "adaptivePlanPhases": [{"trainingPhase": "BUILD", "currentPhase": True}],
        }

        workouts = _normalize_planned_workouts("43075722", detail, "2026-07-01", "2026-07-31")

        # Two rest days (Jul 8, Jul 13) excluded -- 5 real workouts remain.
        assert len(workouts) == 5
        by_date = {w.workout_date: w for w in workouts}
        assert by_date["2026-07-07"].workout_name == "Threshold"
        assert by_date["2026-07-07"].planned_duration_seconds == 3660  # 1:01:00
        assert by_date["2026-07-10"].planned_duration_seconds == 3120  # 52:00
        assert by_date["2026-07-11"].workout_name == "Anaerobic"
        assert by_date["2026-07-11"].planned_duration_seconds == 3000  # 50:00
        assert all(w.plan_id == "43075722" for w in workouts)


class TestNormalizeHrZones:
    def test_normalizes_zone_list(self):
        raw = [
            {"zoneNumber": 1, "zoneLowBoundary": 100, "secsInZone": 120.0},
            {"zoneNumber": 2, "zoneLowBoundary": 140, "secsInZone": 900.0},
        ]

        zones = _normalize_hr_zones(123, raw)

        assert len(zones) == 2
        assert zones[1].zone_number == 2
        assert zones[1].zone_low_boundary_hr == 140
        assert zones[1].seconds_in_zone == 900.0
        assert all(z.activity_id == 123 for z in zones)

    def test_non_list_input_returns_empty(self):
        assert _normalize_hr_zones(123, {"unexpected": "shape"}) == []

    def test_skips_entries_missing_zone_number(self):
        raw = [{"secsInZone": 900.0}]

        assert _normalize_hr_zones(123, raw) == []


class TestNormalizeSamples:
    def test_normalizes_metric_descriptor_columns(self):
        raw = {
            "metricDescriptors": [
                {"key": "sumElapsedDuration", "metricsIndex": 0},
                {"key": "directHeartRate", "metricsIndex": 1},
                {"key": "directSpeed", "metricsIndex": 2},
                {"key": "directElevation", "metricsIndex": 3},
                {"key": "directLatitude", "metricsIndex": 4},
                {"key": "directLongitude", "metricsIndex": 5},
                {"key": "directRunCadence", "metricsIndex": 6},
                {"key": "directTemperature", "metricsIndex": 7},
            ],
            "activityDetailMetrics": [
                {"metrics": [10.0, 150, 2.78, 12.5, 37.0, -122.0, 170.0, 18.5]},
                {"metrics": [20.0, 152, 2.80, 12.8, 37.001, -122.001, 172.0, 18.6]},
            ],
        }

        samples = _normalize_samples(123, raw)

        assert len(samples) == 2
        assert samples[0].activity_id == 123
        assert samples[0].sample_index == 0
        assert samples[0].elapsed_seconds == 10.0
        assert samples[0].heart_rate == 150
        assert samples[0].speed_mps == 2.78
        assert samples[0].pace_sec_per_km == pytest.approx(1000.0 / 2.78)
        assert samples[0].cadence_spm == 170.0
        assert samples[0].elevation_meters == 12.5
        assert samples[0].latitude == 37.0
        assert samples[0].longitude == -122.0
        assert samples[0].temperature_celsius == 18.5
        assert samples[1].sample_index == 1
        assert samples[1].temperature_celsius == 18.6

    def test_missing_descriptors_returns_empty(self):
        assert _normalize_samples(123, {}) == []

    def test_unknown_metric_key_yields_none_field(self):
        raw = {
            "metricDescriptors": [{"key": "someUnknownMetric", "metricsIndex": 0}],
            "activityDetailMetrics": [{"metrics": [42.0]}],
        }

        samples = _normalize_samples(123, raw)

        assert len(samples) == 1
        assert samples[0].heart_rate is None
        assert samples[0].speed_mps is None
        assert samples[0].temperature_celsius is None


class TestDescribeTransportError:
    def test_no_response_returns_bare_message(self):
        exc = requests.exceptions.ConnectionError("connection reset")

        assert describe_transport_error(exc) == "connection reset"

    def test_response_with_cloudflare_headers_and_body_is_appended(self):
        response = MagicMock()
        response.headers = {"server": "cloudflare", "cf-ray": "abc123-SIN"}
        response.text = "<html>Access denied</html>"
        exc = requests.exceptions.HTTPError("401 Client Error: Unauthorized")
        exc.response = response

        described = describe_transport_error(exc)

        assert described.startswith("401 Client Error: Unauthorized (")
        assert "server=cloudflare" in described
        assert "cf-ray=abc123-SIN" in described
        assert "body='<html>Access denied</html>'" in described

    def test_response_with_no_notable_headers_or_body_is_unchanged(self):
        response = MagicMock()
        response.headers = {}
        response.text = ""
        exc = requests.exceptions.HTTPError("500 Server Error")
        exc.response = response

        assert describe_transport_error(exc) == "500 Server Error"

    def test_long_body_is_truncated(self):
        response = MagicMock()
        response.headers = {"server": "nginx"}
        response.text = "x" * 500
        exc = requests.exceptions.HTTPError("403 Forbidden")
        exc.response = response

        described = describe_transport_error(exc)

        assert len(described) < 500 + 100


def make_client(token_dir=None) -> GarminClient:
    client = GarminClient("user@example.com", "hunter2", token_dir=token_dir)
    client._garmin = MagicMock()
    return client


class TestGarminClientLogin:
    def test_login_skips_fresh_login_when_cached_session_loads(self, tmp_path):
        # A valid cached session (from a previous login or bootstrap_login.py run) — no fresh
        # login attempt should happen at all.
        client = make_client(token_dir=str(tmp_path / "tokens"))
        client._garmin.client.is_authenticated = True

        client.login()

        client._garmin.client.load.assert_called_once_with(str(tmp_path / "tokens"))
        client._garmin.login.assert_not_called()

    def test_login_falls_back_to_fresh_login_when_no_cached_session(self, tmp_path):
        client = make_client(token_dir=str(tmp_path / "tokens"))
        client._garmin.client.load.side_effect = GarminConnectConnectionError("no token file")
        client._garmin.login.return_value = (None, None)

        client.login()  # should not raise

        client._garmin.login.assert_called_once_with(tokenstore=str(tmp_path / "tokens"))

    def test_login_falls_back_to_fresh_login_when_cached_tokens_invalid(self, tmp_path):
        client = make_client(token_dir=str(tmp_path / "tokens"))
        client._garmin.client.is_authenticated = False  # loaded, but not actually valid
        client._garmin.login.return_value = (None, None)

        client.login()  # should not raise

        client._garmin.login.assert_called_once_with(tokenstore=str(tmp_path / "tokens"))

    def test_login_without_token_dir_always_attempts_fresh_login(self):
        client = make_client(token_dir=None)
        client._garmin.login.return_value = (None, None)

        client.login()

        client._garmin.client.load.assert_not_called()
        client._garmin.login.assert_called_once_with(tokenstore=None)

    def test_login_wraps_generic_authentication_error(self, tmp_path):
        client = make_client(token_dir=str(tmp_path / "tokens"))
        client._garmin.client.load.side_effect = GarminConnectConnectionError("no token file")
        client._garmin.login.side_effect = GarminConnectAuthenticationError("bad credentials")

        with pytest.raises(GarminAuthError, match="bad credentials"):
            client.login()

    def test_login_wraps_rate_limit_error(self, tmp_path):
        client = make_client(token_dir=str(tmp_path / "tokens"))
        client._garmin.client.load.side_effect = GarminConnectConnectionError("no token file")
        client._garmin.login.side_effect = GarminConnectTooManyRequestsError("429")

        with pytest.raises(GarminAuthError):
            client.login()

    def test_login_wraps_connection_error(self, tmp_path):
        client = make_client(token_dir=str(tmp_path / "tokens"))
        client._garmin.client.load.side_effect = GarminConnectConnectionError("no token file")
        client._garmin.login.side_effect = GarminConnectConnectionError("gateway timeout")

        with pytest.raises(GarminAuthError):
            client.login()

    def test_login_wraps_transport_error(self, tmp_path):
        # garminconnect uses both curl_cffi and plain requests internally depending on the login
        # strategy — a raw transport error must still surface as GarminAuthError, not an
        # unhandled traceback.
        client = make_client(token_dir=str(tmp_path / "tokens"))
        client._garmin.client.load.side_effect = GarminConnectConnectionError("no token file")
        client._garmin.login.side_effect = requests.exceptions.ProxyError(
            "Unable to connect to proxy"
        )

        with pytest.raises(GarminAuthError):
            client.login()

    def test_login_raises_clear_error_when_mfa_required(self, tmp_path):
        # python-garminconnect raises GarminConnectAuthenticationError("MFA Required but no
        # prompt_mfa mechanism supplied") when MFA is needed and no cached session exists (this
        # client passes neither return_on_mfa nor prompt_mfa) — must surface as a specific,
        # actionable GarminAuthError pointing at bootstrap_login.py.
        client = make_client(token_dir=str(tmp_path / "tokens"))
        client._garmin.client.load.side_effect = GarminConnectConnectionError("no token file")
        client._garmin.login.side_effect = GarminConnectAuthenticationError(
            "MFA Required but no prompt_mfa mechanism supplied"
        )

        with pytest.raises(GarminAuthError, match="multi-factor authentication"):
            client.login()

    def test_login_sets_mfa_marker_and_fails_fast_on_next_attempt(self, tmp_path):
        # Once a fresh login has revealed MFA is required, a later sync interval (still no
        # cached session — bootstrap hasn't happened yet) must not repeat a fresh login attempt
        # against Garmin: see PROJECT_PLAN.md's "no auto-retry storms" design guidance.
        token_dir = str(tmp_path / "tokens")
        client = make_client(token_dir=token_dir)
        client._garmin.client.load.side_effect = GarminConnectConnectionError("no token file")
        client._garmin.login.side_effect = GarminConnectAuthenticationError(
            "MFA Required but no prompt_mfa mechanism supplied"
        )

        with pytest.raises(GarminAuthError, match="multi-factor authentication"):
            client.login()
        client._garmin.login.assert_called_once()

        client._garmin.login.reset_mock()
        with pytest.raises(GarminAuthError, match="multi-factor authentication"):
            client.login()
        client._garmin.login.assert_not_called()

    def test_mfa_marker_is_cleared_once_a_session_is_found_valid(self, tmp_path):
        # Simulates bootstrap_login.py (or the web UI) completing the MFA flow in a separate
        # process — the next sync should resume normally, not stay stuck fast-failing forever.
        token_dir = str(tmp_path / "tokens")
        client = make_client(token_dir=token_dir)
        client._garmin.client.load.side_effect = GarminConnectConnectionError("no token file")
        client._garmin.login.side_effect = GarminConnectAuthenticationError(
            "MFA Required but no prompt_mfa mechanism supplied"
        )

        with pytest.raises(GarminAuthError):
            client.login()
        marker_path = os.path.join(token_dir, ".mfa_required")
        assert os.path.exists(marker_path)

        # A cached session now loads successfully (bootstrap completed elsewhere).
        client._garmin.client.load.side_effect = None
        client._garmin.client.is_authenticated = True

        client.login()  # should not raise

        assert not os.path.exists(marker_path)


class TestGarminClientFetch:
    def test_fetch_recent_activities_wraps_connection_error(self):
        client = make_client()
        client._garmin.get_activities.side_effect = GarminConnectConnectionError("boom")

        with pytest.raises(GarminAPIError):
            client.fetch_recent_activities()

    def test_fetch_recent_activities_merges_detail_per_activity(self):
        client = make_client()
        client._garmin.get_activities.return_value = [make_list_item()]
        client._garmin.get_activity.return_value = {
            "summaryDTO": {"distance": 5000.0, "averageSpeed": 2.78}
        }

        activities = client.fetch_recent_activities(limit=5)

        assert len(activities) == 1
        assert activities[0].distance_meters == 5000.0
        client._garmin.get_activities.assert_called_once_with(limit=5)
        client._garmin.get_activity.assert_called_once_with("123")

    def test_fetch_activities_since_merges_detail_per_activity(self):
        client = make_client()
        client._garmin.get_activities_by_date.return_value = [make_list_item()]
        client._garmin.get_activity.return_value = {
            "summaryDTO": {"distance": 5000.0, "averageSpeed": 2.78}
        }

        activities = client.fetch_activities_since("2020-01-01")

        assert len(activities) == 1
        assert activities[0].distance_meters == 5000.0
        client._garmin.get_activities_by_date.assert_called_once_with("2020-01-01")

    def test_fetch_activities_since_empty_when_no_activities(self):
        client = make_client()
        client._garmin.get_activities_by_date.return_value = []

        assert client.fetch_activities_since("2020-01-01") == []

    def test_fetch_activities_since_wraps_connection_error(self):
        client = make_client()
        client._garmin.get_activities_by_date.side_effect = GarminConnectConnectionError("boom")

        with pytest.raises(GarminAPIError):
            client.fetch_activities_since("2020-01-01")

    def test_fetch_activities_since_wraps_transport_error(self):
        client = make_client()
        client._garmin.get_activities_by_date.side_effect = requests.exceptions.ConnectionError(
            "connection reset"
        )

        with pytest.raises(GarminAPIError):
            client.fetch_activities_since("2020-01-01")

    def test_fetch_activities_since_propagates_bad_date_value_error(self):
        # python-garminconnect itself validates the date format before any network call and
        # raises a plain ValueError -- not a GarminAPIError, since this is caller input
        # validation, not a Garmin Connect failure. The web UI catches ValueError separately.
        client = make_client()
        client._garmin.get_activities_by_date.side_effect = ValueError(
            "startdate must be in format 'YYYY-MM-DD', got: not-a-date"
        )

        with pytest.raises(ValueError):
            client.fetch_activities_since("not-a-date")

    def test_fetch_activity_laps_empty_when_no_lap_dtos(self):
        client = make_client()
        client._garmin.get_activity_splits.return_value = {}

        assert client.fetch_activity_laps(123) == []

    def test_fetch_activity_laps_wraps_connection_error(self):
        client = make_client()
        client._garmin.get_activity_splits.side_effect = GarminConnectConnectionError("boom")

        with pytest.raises(GarminAPIError):
            client.fetch_activity_laps(123)

    def test_fetch_activity_laps_wraps_transport_error(self):
        client = make_client()
        client._garmin.get_activity_splits.side_effect = requests.exceptions.ConnectionError(
            "connection reset"
        )

        with pytest.raises(GarminAPIError):
            client.fetch_activity_laps(123)

    def test_fetch_training_baseline_returns_normalized_result(self):
        client = make_client()
        client._garmin.get_lactate_threshold.return_value = {
            "speed_and_heart_rate": {"speed": 3.2, "heartRate": 165}
        }
        client._garmin.get_race_predictions.return_value = {"raceTimeMarathon": 11800}

        baseline = client.fetch_training_baseline()

        assert baseline.lactate_threshold_hr == 165
        assert baseline.race_prediction_marathon_seconds == 11800
        client._garmin.get_lactate_threshold.assert_called_once_with(latest=True)

    def test_fetch_training_baseline_returns_none_on_failure(self):
        # Not every account/device exposes this data -- see GarminClient.fetch_training_baseline's
        # docstring: this must never fail the sync, unlike every other fetch_* method.
        client = make_client()
        client._garmin.get_lactate_threshold.side_effect = GarminConnectConnectionError("boom")

        assert client.fetch_training_baseline() is None

    def test_fetch_daily_wellness_returns_normalized_result(self):
        client = make_client()
        client._garmin.get_sleep_data.return_value = {
            "dailySleepDTO": {"sleepScores": {"overall": {"value": 82}}}
        }
        client._garmin.get_hrv_data.return_value = {"hrvSummary": {"status": "BALANCED"}}
        client._garmin.get_training_status.return_value = {"latestTrainingStatus": "PRODUCTIVE"}
        client._garmin.get_morning_training_readiness.return_value = {"score": 78}
        client._garmin.get_rhr_day.return_value = {"restingHeartRate": 48}

        wellness = client.fetch_daily_wellness("2026-07-06")

        assert wellness.calendar_date == "2026-07-06"
        assert wellness.sleep_score == 82
        assert wellness.hrv_status == "BALANCED"
        assert wellness.training_status_label == "PRODUCTIVE"
        assert wellness.training_readiness_score == 78
        assert wellness.resting_hr == 48
        client._garmin.get_sleep_data.assert_called_once_with("2026-07-06")
        client._garmin.get_rhr_day.assert_called_once_with("2026-07-06")

    def test_fetch_daily_wellness_isolates_one_failing_endpoint(self):
        # The key behavior this milestone deliberately differs from fetch_training_baseline for:
        # one endpoint failing (HRV, here) must not discard data from the other four.
        client = make_client()
        client._garmin.get_sleep_data.return_value = {
            "dailySleepDTO": {"sleepScores": {"overall": {"value": 82}}}
        }
        client._garmin.get_hrv_data.side_effect = GarminConnectConnectionError("no HRV sensor")
        client._garmin.get_training_status.return_value = {"latestTrainingStatus": "PRODUCTIVE"}
        client._garmin.get_morning_training_readiness.return_value = {"score": 78}
        client._garmin.get_rhr_day.return_value = {"restingHeartRate": 48}

        wellness = client.fetch_daily_wellness("2026-07-06")

        assert wellness.hrv_status is None
        assert wellness.hrv_weekly_avg_ms is None
        assert wellness.hrv_last_night_avg_ms is None
        assert wellness.sleep_score == 82
        assert wellness.training_status_label == "PRODUCTIVE"
        assert wellness.training_readiness_score == 78
        assert wellness.resting_hr == 48

    def test_fetch_daily_wellness_returns_all_none_fields_when_everything_fails(self):
        client = make_client()
        client._garmin.get_sleep_data.side_effect = GarminConnectConnectionError("boom")
        client._garmin.get_hrv_data.side_effect = GarminConnectConnectionError("boom")
        client._garmin.get_training_status.side_effect = GarminConnectConnectionError("boom")
        client._garmin.get_morning_training_readiness.side_effect = GarminConnectConnectionError(
            "boom"
        )
        client._garmin.get_rhr_day.side_effect = GarminConnectConnectionError("boom")

        wellness = client.fetch_daily_wellness("2026-07-06")

        assert wellness.calendar_date == "2026-07-06"
        assert wellness.sleep_score is None
        assert wellness.hrv_status is None
        assert wellness.training_status_label is None
        assert wellness.training_readiness_score is None
        assert wellness.resting_hr is None

    def test_fetch_daily_wellness_handles_unexpected_list_shape_from_one_endpoint(self):
        # Same class of bug as fetch_vo2max's list-response regression test -- a sub-fetch
        # returning a list instead of a dict must not crash the final merge step.
        client = make_client()
        client._garmin.get_sleep_data.return_value = [{"dailySleepDTO": {}}]
        client._garmin.get_hrv_data.return_value = {"hrvSummary": {"status": "BALANCED"}}
        client._garmin.get_training_status.return_value = {}
        client._garmin.get_morning_training_readiness.return_value = {}
        client._garmin.get_rhr_day.return_value = {}

        wellness = client.fetch_daily_wellness("2026-07-06")

        assert wellness.calendar_date == "2026-07-06"
        assert wellness.sleep_score is None
        assert wellness.hrv_status == "BALANCED"

    def test_fetch_vo2max_returns_normalized_result(self):
        client = make_client()
        client._garmin.get_max_metrics.return_value = {
            "generic": {"vo2MaxPreciseValue": 52.5},
            "fitnessAge": 28,
        }

        reading = client.fetch_vo2max("2026-07-06")

        assert reading.vo2_max_running == 52.5
        assert reading.fitness_age == 28
        client._garmin.get_max_metrics.assert_called_once_with("2026-07-06")

    def test_fetch_vo2max_returns_none_on_failure(self):
        # Not every device estimates VO2 max -- see GarminClient.fetch_vo2max's docstring: this
        # must never fail the sync, matching fetch_training_baseline's contract.
        client = make_client()
        client._garmin.get_max_metrics.side_effect = GarminConnectConnectionError("boom")

        assert client.fetch_vo2max("2026-07-06") is None

    def test_fetch_vo2max_unwraps_the_real_list_wrapped_response(self):
        # Regression test: get_max_metrics' real successful response is a list containing one
        # dict, not a bare dict. An earlier guard (added after a real crash on a list response)
        # short-circuited any list straight to None before ever normalizing it -- silently
        # discarding every real VO2 max reading. Fixed by unwrapping inside _normalize_vo2max
        # instead of bailing out here (see its docstring for the full history).
        client = make_client()
        client._garmin.get_max_metrics.return_value = [{"generic": {"vo2MaxValue": 50.0}}]

        reading = client.fetch_vo2max("2026-07-06")

        assert reading is not None
        assert reading.vo2_max_running == 50.0

    def test_fetch_vo2max_returns_none_on_list_with_no_dict_element(self):
        client = make_client()
        client._garmin.get_max_metrics.return_value = ["not-a-dict"]

        reading = client.fetch_vo2max("2026-07-06")

        assert reading is not None
        assert reading.vo2_max_running is None

    def test_fetch_planned_workouts_returns_normalized_result(self):
        client = make_client()
        client._garmin.get_training_plans.return_value = [{"planId": "plan-1"}]
        client._garmin.get_training_plan_by_id.return_value = {
            "workouts": [
                {"date": "2026-07-06", "taskWorkout": {"workoutName": "Tempo Run"}}
            ]
        }

        workouts = client.fetch_planned_workouts("2026-07-01", "2026-07-10")

        assert len(workouts) == 1
        assert workouts[0].plan_id == "plan-1"
        assert workouts[0].workout_name == "Tempo Run"
        client._garmin.get_training_plan_by_id.assert_called_once_with("plan-1")

    def test_fetch_planned_workouts_extracts_trainingplanlist_key(self):
        # get_training_plans()'s real top-level key, confirmed directly from
        # python-garminconnect's own demo.py ("resp.get('trainingPlanList') or []") -- not a
        # guess. This was the actual cause of a live "0 planned workouts" report: the prior code
        # only checked "trainingPlans"/"plans", so a real trainingPlanList-shaped response fell
        # through to plan_list=None and returned [] silently.
        client = make_client()
        client._garmin.get_training_plans.return_value = {
            "trainingPlanList": [{"planId": "plan-1"}]
        }
        client._garmin.get_training_plan_by_id.return_value = {
            "workouts": [{"date": "2026-07-06", "workoutName": "Tempo Run"}]
        }

        workouts = client.fetch_planned_workouts("2026-07-01", "2026-07-10")

        assert len(workouts) == 1
        assert workouts[0].plan_id == "plan-1"

    def test_fetch_planned_workouts_extracts_trainingplanid_key(self):
        # Confirmed live against a real account with an active plan (via the Diagnostics panel):
        # a plan entry's own id field is "trainingPlanId" (an integer), not "planId"/"id" as
        # originally guessed -- this was the actual remaining cause of "0 planned workouts" even
        # after the trainingPlanList fix, since plan_id extraction failed and every plan was
        # silently skipped.
        client = make_client()
        client._garmin.get_training_plans.return_value = {
            "trainingPlanList": [{"trainingPlanId": 43075722, "trainingPlanCategory": "FBT_BASIC"}]
        }
        client._garmin.get_training_plan_by_id.return_value = {
            "workouts": [{"date": "2026-07-06", "workoutName": "Tempo Run"}]
        }

        workouts = client.fetch_planned_workouts("2026-07-01", "2026-07-10")

        assert len(workouts) == 1
        assert workouts[0].plan_id == "43075722"
        client._garmin.get_training_plan_by_id.assert_called_once_with(43075722)

    def test_fetch_planned_workouts_routes_adaptive_plans_to_the_adaptive_endpoint(self):
        # demo.py routes trainingPlanCategory == "FBT_ADAPTIVE" to
        # get_adaptive_training_plan_by_id instead of the phased get_training_plan_by_id --
        # confirmed live: the same real account's active plan is FBT_ADAPTIVE.
        client = make_client()
        client._garmin.get_training_plans.return_value = {
            "trainingPlanList": [
                {"trainingPlanId": 43075722, "trainingPlanCategory": "FBT_ADAPTIVE"}
            ]
        }
        client._garmin.get_adaptive_training_plan_by_id.return_value = {
            "workouts": [
                {"date": "2026-07-06", "taskWorkout": {"workoutName": "Adaptive Run"}}
            ]
        }

        workouts = client.fetch_planned_workouts("2026-07-01", "2026-07-10")

        assert len(workouts) == 1
        assert workouts[0].workout_name == "Adaptive Run"
        client._garmin.get_adaptive_training_plan_by_id.assert_called_once_with(43075722)
        client._garmin.get_training_plan_by_id.assert_not_called()

    def test_fetch_planned_workouts_routes_non_adaptive_plans_to_the_phased_endpoint(self):
        client = make_client()
        client._garmin.get_training_plans.return_value = {
            "trainingPlanList": [{"planId": "plan-1", "trainingPlanCategory": "FBT_BASIC"}]
        }
        client._garmin.get_training_plan_by_id.return_value = {
            "workouts": [{"date": "2026-07-06", "workoutName": "Tempo Run"}]
        }

        workouts = client.fetch_planned_workouts("2026-07-01", "2026-07-10")

        assert len(workouts) == 1
        client._garmin.get_training_plan_by_id.assert_called_once_with("plan-1")
        client._garmin.get_adaptive_training_plan_by_id.assert_not_called()

    def test_fetch_planned_workouts_returns_empty_when_no_plans(self):
        client = make_client()
        client._garmin.get_training_plans.return_value = []

        assert client.fetch_planned_workouts("2026-07-01", "2026-07-10") == []

    def test_fetch_planned_workouts_returns_empty_when_plan_list_fetch_fails(self):
        client = make_client()
        client._garmin.get_training_plans.side_effect = GarminConnectConnectionError("boom")

        assert client.fetch_planned_workouts("2026-07-01", "2026-07-10") == []

    def test_fetch_planned_workouts_isolates_one_failing_plan_from_siblings(self):
        # A failure fetching one plan's detail must not discard workouts from sibling plans.
        client = make_client()
        client._garmin.get_training_plans.return_value = [
            {"planId": "plan-1"},
            {"planId": "plan-2"},
        ]

        def get_plan_by_id(plan_id):
            if plan_id == "plan-1":
                return {"workouts": [{"date": "2026-07-06", "workoutName": "Plan 1 Run"}]}
            raise GarminConnectConnectionError("boom")

        client._garmin.get_training_plan_by_id.side_effect = get_plan_by_id

        workouts = client.fetch_planned_workouts("2026-07-01", "2026-07-10")

        assert len(workouts) == 1
        assert workouts[0].plan_id == "plan-1"

    def test_fetch_activity_hr_zones_returns_normalized_result(self):
        client = make_client()
        client._garmin.get_activity_hr_in_timezones.return_value = [
            {"zoneNumber": 1, "zoneLowBoundary": 100, "secsInZone": 120.0}
        ]

        zones = client.fetch_activity_hr_zones(123)

        assert len(zones) == 1
        assert zones[0].zone_number == 1
        client._garmin.get_activity_hr_in_timezones.assert_called_once_with("123")

    def test_fetch_activity_hr_zones_returns_empty_on_failure(self):
        client = make_client()
        client._garmin.get_activity_hr_in_timezones.side_effect = GarminConnectConnectionError(
            "boom"
        )

        assert client.fetch_activity_hr_zones(123) == []

    def test_fetch_activity_samples_returns_normalized_result(self):
        client = make_client()
        client._garmin.get_activity_details.return_value = {
            "metricDescriptors": [{"key": "directHeartRate", "metricsIndex": 0}],
            "activityDetailMetrics": [{"metrics": [150]}],
        }

        samples = client.fetch_activity_samples(123)

        assert len(samples) == 1
        assert samples[0].heart_rate == 150
        client._garmin.get_activity_details.assert_called_once_with("123")

    def test_fetch_activity_samples_returns_empty_on_failure(self):
        client = make_client()
        client._garmin.get_activity_details.side_effect = GarminConnectConnectionError("boom")

        assert client.fetch_activity_samples(123) == []

    def test_fetch_diagnostic_training_plans_returns_raw_response(self):
        client = make_client()
        client._garmin.get_training_plans.return_value = {"trainingPlanList": [{"planId": "p1"}]}

        assert client.fetch_diagnostic("training_plans") == {
            "trainingPlanList": [{"planId": "p1"}]
        }

    def test_fetch_diagnostic_training_plan_detail_returns_raw_response(self):
        client = make_client()
        client._garmin.get_training_plans.return_value = {
            "trainingPlanList": [{"planId": "p1", "trainingPlanCategory": "FBT_BASIC"}]
        }
        client._garmin.get_training_plan_by_id.return_value = {"workouts": ["raw"]}

        result = client.fetch_diagnostic("training_plan_detail")

        assert result == {"workouts": ["raw"]}
        client._garmin.get_training_plan_by_id.assert_called_once_with("p1")

    def test_fetch_diagnostic_training_plan_detail_routes_adaptive_plans(self):
        client = make_client()
        client._garmin.get_training_plans.return_value = {
            "trainingPlanList": [{"planId": "p1", "trainingPlanCategory": "FBT_ADAPTIVE"}]
        }
        client._garmin.get_adaptive_training_plan_by_id.return_value = {"workouts": ["adaptive"]}

        result = client.fetch_diagnostic("training_plan_detail")

        assert result == {"workouts": ["adaptive"]}
        client._garmin.get_adaptive_training_plan_by_id.assert_called_once_with("p1")

    def test_fetch_diagnostic_training_plan_detail_reports_no_plans_found(self):
        client = make_client()
        client._garmin.get_training_plans.return_value = {"trainingPlanList": []}

        result = client.fetch_diagnostic("training_plan_detail")

        assert "No training plans found" in result["note"]

    def test_fetch_diagnostic_training_plan_detail_extracts_trainingplanid_key(self):
        client = make_client()
        client._garmin.get_training_plans.return_value = {
            "trainingPlanList": [{"trainingPlanId": 43075722, "trainingPlanCategory": "FBT_BASIC"}]
        }
        client._garmin.get_training_plan_by_id.return_value = {"workouts": ["raw"]}

        result = client.fetch_diagnostic("training_plan_detail")

        assert result == {"workouts": ["raw"]}
        client._garmin.get_training_plan_by_id.assert_called_once_with(43075722)

    def test_fetch_diagnostic_scheduled_workouts_returns_raw_response(self):
        client = make_client()
        client._garmin.get_scheduled_workouts.return_value = {"raw": "calendar-data"}

        result = client.fetch_diagnostic("scheduled_workouts")

        assert result == {"raw": "calendar-data"}
        client._garmin.get_scheduled_workouts.assert_called_once()

    def test_fetch_diagnostic_sleep_data_returns_raw_response(self):
        client = make_client()
        client._garmin.get_sleep_data.return_value = {"dailySleepDTO": {"sleepTimeSeconds": 100}}

        result = client.fetch_diagnostic("sleep_data")

        assert result == {"dailySleepDTO": {"sleepTimeSeconds": 100}}
        client._garmin.get_sleep_data.assert_called_once()

    def test_fetch_diagnostic_hrv_data_returns_raw_response(self):
        client = make_client()
        client._garmin.get_hrv_data.return_value = {"hrvSummary": {"status": "BALANCED"}}

        result = client.fetch_diagnostic("hrv_data")

        assert result == {"hrvSummary": {"status": "BALANCED"}}
        client._garmin.get_hrv_data.assert_called_once()

    def test_fetch_diagnostic_training_status_returns_raw_response(self):
        client = make_client()
        client._garmin.get_training_status.return_value = {"latestTrainingStatus": "PRODUCTIVE"}

        result = client.fetch_diagnostic("training_status")

        assert result == {"latestTrainingStatus": "PRODUCTIVE"}
        client._garmin.get_training_status.assert_called_once()

    def test_fetch_diagnostic_training_readiness_returns_raw_response(self):
        client = make_client()
        client._garmin.get_morning_training_readiness.return_value = {"score": 72}

        result = client.fetch_diagnostic("training_readiness")

        assert result == {"score": 72}
        client._garmin.get_morning_training_readiness.assert_called_once()

    def test_fetch_diagnostic_resting_hr_latest_returns_most_recent_available_date(self):
        # "Latest" (not "today") because today's resting HR can legitimately be unavailable if
        # Garmin hasn't finalized it yet -- that shouldn't look like a wrong field-name guess.
        client = make_client()
        today = datetime.now(timezone.utc).date()
        three_days_ago = (today - timedelta(days=3)).isoformat()

        def _rhr_side_effect(cdate):
            if cdate == three_days_ago:
                return {"restingHeartRate": 48}
            return {"restingHeartRate": None}

        client._garmin.get_rhr_day.side_effect = _rhr_side_effect

        result = client.fetch_diagnostic("resting_hr_latest")

        assert result == {"date": three_days_ago, "raw": {"restingHeartRate": 48}}
        assert client._garmin.get_rhr_day.call_count == 4  # today, -1, -2, -3

    def test_fetch_diagnostic_resting_hr_latest_reports_no_data_found(self):
        client = make_client()
        client._garmin.get_rhr_day.return_value = {"restingHeartRate": None}

        result = client.fetch_diagnostic("resting_hr_latest")

        assert result["date"] is None
        assert "No data found" in result["note"]
        assert client._garmin.get_rhr_day.call_count == 14

    def test_fetch_diagnostic_vo2max_latest_returns_most_recent_available_date(self):
        client = make_client()
        today = datetime.now(timezone.utc).date()
        two_days_ago = (today - timedelta(days=2)).isoformat()

        def _vo2max_side_effect(cdate):
            if cdate == two_days_ago:
                return {"generic": {"vo2MaxValue": 51.2}}
            return {"generic": {"vo2MaxValue": None}}

        client._garmin.get_max_metrics.side_effect = _vo2max_side_effect

        result = client.fetch_diagnostic("vo2max_latest")

        assert result == {"date": two_days_ago, "raw": {"generic": {"vo2MaxValue": 51.2}}}
        assert client._garmin.get_max_metrics.call_count == 3  # today, -1, -2

    def test_fetch_diagnostic_unknown_check_raises_value_error(self):
        client = make_client()

        with pytest.raises(ValueError, match="Unknown diagnostic check"):
            client.fetch_diagnostic("not_a_real_check")

    def test_fetch_diagnostic_propagates_raw_exceptions(self):
        # Unlike every other fetch_* method, fetch_diagnostic must NOT swallow failures --
        # seeing the raw exception is the entire point of a diagnostic tool.
        client = make_client()
        client._garmin.get_training_plans.side_effect = GarminConnectConnectionError("boom")

        with pytest.raises(GarminConnectConnectionError):
            client.fetch_diagnostic("training_plans")
