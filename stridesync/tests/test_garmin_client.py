import os
from unittest.mock import MagicMock, PropertyMock

import pytest
import requests
from garmy import ActivitySummary
from garmy.core.exceptions import APIError, AuthError, LoginError

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
    def test_login_skips_when_already_authenticated(self):
        # A valid cached session (from a previous login or bootstrap_login.py run) — no API
        # call should happen at all.
        client = GarminClient("user@example.com", "hunter2")
        client._auth_client = MagicMock()
        client._auth_client.is_authenticated = True
        client._api_client = MagicMock()

        client.login()

        client._api_client.login.assert_not_called()

    def test_login_refreshes_when_session_expired_but_refreshable(self):
        client = GarminClient("user@example.com", "hunter2")
        client._auth_client = MagicMock()
        client._auth_client.is_authenticated = False
        client._auth_client.needs_refresh = True
        client._api_client = MagicMock()

        client.login()

        client._auth_client.refresh_tokens.assert_called_once()
        client._api_client.login.assert_not_called()

    def test_login_falls_back_to_fresh_login_when_refresh_fails(self):
        # The cached session itself was revoked/invalid server-side — refresh_tokens() raises,
        # and login() should fall back to a fresh login rather than giving up.
        client = GarminClient("user@example.com", "hunter2")
        client._auth_client = MagicMock()
        type(client._auth_client).is_authenticated = PropertyMock(side_effect=[False, True])
        client._auth_client.needs_refresh = True
        client._auth_client.refresh_tokens.side_effect = AuthError("refresh token revoked")
        client._api_client = MagicMock()

        client.login()  # should not raise

        client._auth_client.refresh_tokens.assert_called_once()
        client._api_client.login.assert_called_once_with("user@example.com", "hunter2")

    def test_login_wraps_transport_error_during_refresh(self):
        client = GarminClient("user@example.com", "hunter2")
        client._auth_client = MagicMock()
        client._auth_client.is_authenticated = False
        client._auth_client.needs_refresh = True
        client._auth_client.refresh_tokens.side_effect = requests.exceptions.ConnectionError(
            "connection reset"
        )
        client._api_client = MagicMock()

        with pytest.raises(GarminAuthError):
            client.login()

        client._api_client.login.assert_not_called()

    def test_login_wraps_auth_error(self):
        client = GarminClient("user@example.com", "hunter2")
        client._auth_client = MagicMock()
        client._auth_client.is_authenticated = False
        client._auth_client.needs_refresh = False
        client._api_client = MagicMock()
        client._api_client.login.side_effect = LoginError("bad credentials")

        with pytest.raises(GarminAuthError):
            client.login()

    def test_login_requires_valid_tokens(self):
        client = GarminClient("user@example.com", "hunter2")
        client._auth_client = MagicMock()
        client._auth_client.is_authenticated = False
        client._auth_client.needs_refresh = False
        client._api_client = MagicMock()
        client._api_client.login.return_value = None

        with pytest.raises(GarminAuthError):
            client.login()

    def test_login_success_via_fresh_login(self):
        client = GarminClient("user@example.com", "hunter2")
        client._auth_client = MagicMock()
        type(client._auth_client).is_authenticated = PropertyMock(side_effect=[False, True])
        client._auth_client.needs_refresh = False
        client._api_client = MagicMock()

        client.login()  # should not raise

        client._api_client.login.assert_called_once_with("user@example.com", "hunter2")

    def test_login_raises_clear_error_when_mfa_required(self):
        # garmy doesn't raise when the account needs MFA and no prompt_mfa callback was
        # given (we never pass one, since this runs headless) — it returns
        # ("needs_mfa", state) instead. This must surface as a specific, actionable
        # GarminAuthError pointing at bootstrap_login.py, not the generic "did not return
        # valid tokens" message.
        client = GarminClient("user@example.com", "hunter2")
        client._auth_client = MagicMock()
        client._auth_client.is_authenticated = False
        client._auth_client.needs_refresh = False
        client._api_client = MagicMock()
        client._api_client.login.return_value = ("needs_mfa", {"csrf_token": "abc"})

        with pytest.raises(GarminAuthError, match="multi-factor authentication"):
            client.login()

    def test_login_sets_mfa_marker_and_fails_fast_on_next_attempt(self, tmp_path):
        # Once a fresh login has revealed MFA is required, a later sync interval (still no
        # cached session — bootstrap hasn't happened yet) must not repeat a fresh SSO login
        # against Garmin: see PROJECT_PLAN.md's "no auto-retry storms" design guidance.
        token_dir = str(tmp_path / "tokens")
        client = GarminClient("user@example.com", "hunter2", token_dir=token_dir)
        client._auth_client = MagicMock()
        client._auth_client.is_authenticated = False
        client._auth_client.needs_refresh = False
        client._api_client = MagicMock()
        client._api_client.login.return_value = ("needs_mfa", {"csrf_token": "abc"})

        with pytest.raises(GarminAuthError, match="multi-factor authentication"):
            client.login()
        client._api_client.login.assert_called_once()

        client._api_client.login.reset_mock()
        with pytest.raises(GarminAuthError, match="multi-factor authentication"):
            client.login()
        client._api_client.login.assert_not_called()

    def test_mfa_marker_is_cleared_once_a_session_is_found_valid(self, tmp_path):
        # Simulates bootstrap_login.py (or the web UI) completing the MFA flow in a separate
        # process — the next sync should resume normally, not stay stuck fast-failing forever.
        token_dir = str(tmp_path / "tokens")
        client = GarminClient("user@example.com", "hunter2", token_dir=token_dir)
        client._auth_client = MagicMock()
        client._auth_client.is_authenticated = False
        client._auth_client.needs_refresh = False
        client._api_client = MagicMock()
        client._api_client.login.return_value = ("needs_mfa", {"csrf_token": "abc"})

        with pytest.raises(GarminAuthError):
            client.login()
        marker_path = os.path.join(token_dir, ".mfa_required")
        assert os.path.exists(marker_path)

        client._auth_client.is_authenticated = True

        client.login()  # should not raise

        assert not os.path.exists(marker_path)

    def test_login_wraps_transport_error(self):
        # garmy's SSO flow doesn't wrap connection/proxy/timeout failures in its own
        # exceptions — a raw requests error must still surface as GarminAuthError, not an
        # unhandled traceback (see garmin_client.py module docstring / _TRANSPORT_ERRORS).
        client = GarminClient("user@example.com", "hunter2")
        client._auth_client = MagicMock()
        client._auth_client.is_authenticated = False
        client._auth_client.needs_refresh = False
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
