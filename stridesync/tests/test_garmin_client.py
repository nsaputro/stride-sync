from unittest.mock import MagicMock

import pytest
import requests
from garmy import ActivitySummary
from garmy.core.exceptions import APIError, LoginError

from app.sync.garmin_client import (
    GarminAPIError,
    GarminAuthError,
    GarminClient,
    _normalize_activity,
    _normalize_lap,
    _pace_sec_per_km,
)


def make_summary(**overrides) -> ActivitySummary:
    defaults = dict(
        activity_id=123,
        activity_name="Morning Run",
        start_time_local="2026-06-01 06:30:00",
        start_time_gmt="2026-06-01 13:30:00",
        activity_type={"typeKey": "running"},
        duration=1800.0,
        moving_duration=1750.0,
        average_hr=150,
        max_hr=172,
        aerobic_training_effect=3.2,
        anaerobic_training_effect=0.5,
        training_effect_label="TEMPO",
        activity_training_load=85.0,
    )
    defaults.update(overrides)
    return ActivitySummary(**defaults)


class TestPaceConversion:
    def test_positive_speed(self):
        assert _pace_sec_per_km(2.5) == pytest.approx(400.0)

    def test_zero_speed_is_none(self):
        assert _pace_sec_per_km(0) is None

    def test_missing_speed_is_none(self):
        assert _pace_sec_per_km(None) is None


class TestNormalizeActivity:
    def test_merges_summary_and_detail(self):
        summary = make_summary()
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

        activity = _normalize_activity(summary, detail)

        assert activity.activity_id == 123
        assert activity.activity_type == "running"
        assert activity.distance_meters == 5000.0
        assert activity.average_speed_mps == 2.78
        assert activity.average_pace_sec_per_km == pytest.approx(1000.0 / 2.78)
        assert activity.average_cadence_spm == 170.0
        assert activity.max_cadence_spm == 182.0
        assert activity.elevation_gain_meters == 45.0
        assert activity.calories == 320.0
        # Summary-only fields still come through
        assert activity.average_hr == 150
        assert activity.activity_training_load == 85.0

    def test_missing_detail_does_not_crash(self):
        summary = make_summary()
        activity = _normalize_activity(summary, {})

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


class TestGarminClientLogin:
    def test_login_wraps_auth_error(self):
        client = GarminClient("user@example.com", "hunter2")
        client._api_client = MagicMock()
        client._api_client.login.side_effect = LoginError("bad credentials")

        with pytest.raises(GarminAuthError):
            client.login()

    def test_login_requires_valid_tokens(self):
        client = GarminClient("user@example.com", "hunter2")
        client._api_client = MagicMock()
        client._api_client.login.return_value = None
        client._api_client.is_authenticated = False

        with pytest.raises(GarminAuthError):
            client.login()

    def test_login_success(self):
        client = GarminClient("user@example.com", "hunter2")
        client._api_client = MagicMock()
        client._api_client.is_authenticated = True

        client.login()  # should not raise

    def test_login_wraps_transport_error(self):
        # garmy's SSO flow doesn't wrap connection/proxy/timeout failures in its own
        # exceptions — a raw requests error must still surface as GarminAuthError, not an
        # unhandled traceback (see garmin_client.py module docstring / _TRANSPORT_ERRORS).
        client = GarminClient("user@example.com", "hunter2")
        client._api_client = MagicMock()
        client._api_client.login.side_effect = requests.exceptions.ProxyError(
            "Unable to connect to proxy"
        )

        with pytest.raises(GarminAuthError):
            client.login()


class TestGarminClientFetch:
    def test_fetch_recent_activities_wraps_api_error(self):
        client = GarminClient("user@example.com", "hunter2")
        client._api_client = MagicMock()
        client._api_client.metrics.get.return_value.list.side_effect = APIError(
            msg="boom", error=Exception("network down")
        )

        with pytest.raises(GarminAPIError):
            client.fetch_recent_activities()

    def test_fetch_recent_activities_merges_detail_per_activity(self):
        client = GarminClient("user@example.com", "hunter2")
        client._api_client = MagicMock()
        client._api_client.metrics.get.return_value.list.return_value = [make_summary()]
        client._api_client.connectapi.return_value = {
            "summaryDTO": {"distance": 5000.0, "averageSpeed": 2.78}
        }

        activities = client.fetch_recent_activities(limit=5)

        assert len(activities) == 1
        assert activities[0].distance_meters == 5000.0
        client._api_client.metrics.get.return_value.list.assert_called_once_with(limit=5)

    def test_fetch_activity_laps_empty_when_no_lap_dtos(self):
        client = GarminClient("user@example.com", "hunter2")
        client._api_client = MagicMock()
        client._api_client.connectapi.return_value = {}

        assert client.fetch_activity_laps(123) == []

    def test_fetch_activity_laps_wraps_api_error(self):
        client = GarminClient("user@example.com", "hunter2")
        client._api_client = MagicMock()
        client._api_client.connectapi.side_effect = APIError(
            msg="boom", error=Exception("timeout")
        )

        with pytest.raises(GarminAPIError):
            client.fetch_activity_laps(123)

    def test_fetch_activity_laps_wraps_transport_error(self):
        client = GarminClient("user@example.com", "hunter2")
        client._api_client = MagicMock()
        client._api_client.connectapi.side_effect = requests.exceptions.ConnectionError(
            "connection reset"
        )

        with pytest.raises(GarminAPIError):
            client.fetch_activity_laps(123)
