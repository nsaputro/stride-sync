import os
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
    _normalize_hr_zones,
    _normalize_lap,
    _normalize_samples,
    _normalize_training_baseline,
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
            ],
            "activityDetailMetrics": [
                {"metrics": [10.0, 150, 2.78, 12.5, 37.0, -122.0, 170.0]},
                {"metrics": [20.0, 152, 2.80, 12.8, 37.001, -122.001, 172.0]},
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
        assert samples[1].sample_index == 1

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
