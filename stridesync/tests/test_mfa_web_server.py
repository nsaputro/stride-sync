from unittest.mock import MagicMock, patch

import pytest
import requests
from starlette.testclient import TestClient

from app.mfa_web import server as mfa_web_server
from app.config import Settings
from garminconnect import GarminConnectAuthenticationError


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


@pytest.fixture(autouse=True)
def _reset_pending_state():
    # mfa_web.server keeps one in-process pending-login slot (see its module docstring) —
    # reset it around every test so state can't leak between them.
    mfa_web_server._pending_garmin = None
    yield
    mfa_web_server._pending_garmin = None


def _client(tmp_path) -> TestClient:
    app = mfa_web_server.create_app(make_settings(tmp_path))
    return TestClient(app)


def test_index_shows_not_logged_in_when_no_session(tmp_path):
    response = _client(tmp_path).get("/")

    assert response.status_code == 200
    assert "No valid Garmin Connect session" in response.text
    assert 'action="sync"' not in response.text


def test_index_shows_logged_in_when_session_cached(tmp_path):
    token_dir = tmp_path / "garmin_tokens"
    token_dir.mkdir()
    (token_dir / "garmin_tokens.json").write_text("{}")

    response = _client(tmp_path).get("/")

    assert response.status_code == 200
    assert "Already logged in" in response.text
    assert 'action="sync"' in response.text


def test_start_reports_clear_error_when_credentials_missing(tmp_path):
    # Real production incident: the mfa-web s6 service's `run` script never exported
    # GARMIN_USERNAME/GARMIN_PASSWORD (unlike sync-scheduler's), so Settings always saw empty
    # credentials and the first login attempt (no cached session yet, the whole point of this
    # UI) hit garminconnect's generic "Username and password are required" — this checks the
    # app-level guard added alongside the run-script fix, so a misconfigured install still fails
    # clearly instead of relying on the library's message.
    settings = make_settings(tmp_path)
    blank_settings = Settings(**{**settings.__dict__, "garmin_username": "", "garmin_password": ""})
    app = mfa_web_server.create_app(blank_settings)
    client = TestClient(app)

    response = client.post("/start")

    assert response.status_code == 200
    assert "garmin_username and garmin_password are not set" in response.text


def test_start_success_without_mfa(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = (None, None)
        mock_cls.return_value = mock_garmin

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert (
        "No valid Garmin Connect session" in response.text
        or "Already logged in" in response.text
    )


def test_start_wraps_auth_error(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.side_effect = GarminConnectAuthenticationError("bad credentials")
        mock_cls.return_value = mock_garmin

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert "Login failed" in response.text
    assert "bad credentials" in response.text


def test_start_wraps_transport_error(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.side_effect = requests.exceptions.ConnectionError("no route")
        mock_cls.return_value = mock_garmin

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert "Could not reach Garmin Connect" in response.text


def test_start_never_returns_a_raw_500_on_unexpected_error(tmp_path):
    # A real production incident: an exception other than GarminConnectAuthenticationError (e.g.
    # an unexpected response shape from Garmin) and this route had no catch-all, so it crashed to
    # Starlette's generic 500 page instead of a diagnosable message.
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.side_effect = ValueError("unexpected Garmin response shape")
        mock_cls.return_value = mock_garmin

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert "Login failed unexpectedly" in response.text


def test_start_needs_mfa_then_verify_succeeds(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = ("needs_mfa", None)
        mock_cls.return_value = mock_garmin

        client = _client(tmp_path)
        start_response = client.post("/start")
        assert "multi-factor authentication code" in start_response.text

        verify_response = client.post("/verify", data={"code": "123456"})

    assert verify_response.status_code == 200
    assert "Logged in successfully" in verify_response.text
    mock_garmin.resume_login.assert_called_once_with({}, "123456")
    assert mfa_web_server._pending_garmin is None
    # Regression check: a real production incident where a "successful" MFA login was never
    # actually saved, because Garmin.login()/resume_login() skip persisting to disk on the
    # return_on_mfa=True path this module has to use (see mfa_login.py's module docstring) — the
    # web UI kept showing "not logged in" even after login had genuinely succeeded.
    mock_garmin.client.dump.assert_called_once_with(str(tmp_path / "garmin_tokens"))


def test_verify_wraps_auth_error(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = ("needs_mfa", None)
        mock_garmin.resume_login.side_effect = GarminConnectAuthenticationError(
            "MFA verification failed"
        )
        mock_cls.return_value = mock_garmin

        client = _client(tmp_path)
        client.post("/start")
        verify_response = client.post("/verify", data={"code": "000000"})

    assert verify_response.status_code == 200
    assert "MFA verification failed" in verify_response.text


def test_verify_wraps_transport_error(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = ("needs_mfa", None)
        mock_garmin.resume_login.side_effect = requests.exceptions.Timeout("timed out")
        mock_cls.return_value = mock_garmin

        client = _client(tmp_path)
        client.post("/start")
        verify_response = client.post("/verify", data={"code": "000000"})

    assert verify_response.status_code == 200
    assert "Could not reach Garmin Connect" in verify_response.text


def test_verify_never_returns_a_raw_500_on_unexpected_error(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = ("needs_mfa", None)
        mock_garmin.resume_login.side_effect = ValueError("unexpected Garmin response shape")
        mock_cls.return_value = mock_garmin

        client = _client(tmp_path)
        client.post("/start")
        verify_response = client.post("/verify", data={"code": "000000"})

    assert verify_response.status_code == 200
    assert "Verification failed unexpectedly" in verify_response.text


def test_verify_without_pending_flow_shows_error(tmp_path):
    response = _client(tmp_path).post("/verify", data={"code": "123456"})

    assert response.status_code == 200
    assert "No login is currently waiting" in response.text


def test_sync_route_reports_activity_count(tmp_path):
    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_sync_once", return_value=5
    ) as mock_run:
        response = _client(tmp_path).post("/sync")

    assert response.status_code == 200
    assert "Synced 5 activities" in response.text
    mock_run.assert_called_once()


def test_sync_route_uses_singular_wording_for_one_activity(tmp_path):
    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_sync_once", return_value=1
    ):
        response = _client(tmp_path).post("/sync")

    assert response.status_code == 200
    assert "Synced 1 activity." in response.text


def test_sync_route_wraps_auth_error(tmp_path):
    from app.sync.garmin_client import GarminAuthError

    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_sync_once",
        side_effect=GarminAuthError("requires a multi-factor authentication (MFA) code"),
    ):
        response = _client(tmp_path).post("/sync")

    assert response.status_code == 200
    assert "Sync failed" in response.text
    assert "multi-factor authentication" in response.text


def test_sync_route_wraps_api_error(tmp_path):
    from app.sync.garmin_client import GarminAPIError

    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_sync_once", side_effect=GarminAPIError("Failed to fetch activities")
    ):
        response = _client(tmp_path).post("/sync")

    assert response.status_code == 200
    assert "Sync failed" in response.text
    assert "Failed to fetch activities" in response.text


def test_sync_route_never_returns_a_raw_500_on_unexpected_error(tmp_path):
    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_sync_once", side_effect=ValueError("unexpected shape")
    ):
        response = _client(tmp_path).post("/sync")

    assert response.status_code == 200
    assert "Sync failed unexpectedly" in response.text
