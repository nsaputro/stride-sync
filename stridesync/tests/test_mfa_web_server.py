from unittest.mock import MagicMock, patch

import pytest
import requests
from starlette.testclient import TestClient

from app.mfa_web import server as mfa_web_server
from app.config import Settings
from garmy.core.exceptions import AuthError


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
    mfa_web_server._pending_auth_client = None
    mfa_web_server._pending_mfa_state = None
    yield
    mfa_web_server._pending_auth_client = None
    mfa_web_server._pending_mfa_state = None


def _client(tmp_path) -> TestClient:
    app = mfa_web_server.create_app(make_settings(tmp_path))
    return TestClient(app)


def test_index_shows_not_logged_in_when_no_session(tmp_path):
    with patch("app.mfa_web.server.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_cls.return_value = mock_auth

        response = _client(tmp_path).get("/")

    assert response.status_code == 200
    assert "No valid Garmin Connect session" in response.text


def test_index_shows_logged_in_when_session_cached(tmp_path):
    with patch("app.mfa_web.server.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = True
        mock_cls.return_value = mock_auth

        response = _client(tmp_path).get("/")

    assert response.status_code == 200
    assert "Already logged in" in response.text


def test_start_success_without_mfa(tmp_path):
    with patch("app.mfa_web.server.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_auth.login.return_value = (object(), object())
        mock_cls.return_value = mock_auth

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert "No valid Garmin Connect session" in response.text or "Already logged in" in response.text


def test_start_wraps_auth_error(tmp_path):
    with patch("app.mfa_web.server.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_auth.login.side_effect = AuthError("bad credentials")
        mock_cls.return_value = mock_auth

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert "Login failed" in response.text
    assert "bad credentials" in response.text


def test_start_wraps_transport_error(tmp_path):
    with patch("app.mfa_web.server.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_auth.login.side_effect = requests.exceptions.ConnectionError("no route")
        mock_cls.return_value = mock_auth

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert "Could not reach Garmin Connect" in response.text


def test_start_never_returns_a_raw_500_on_unexpected_error(tmp_path):
    # A real production incident: garmy raised something other than AuthError (e.g. an
    # unexpected response shape from Garmin) and this route had no catch-all, so it crashed to
    # Starlette's generic 500 page instead of a diagnosable message.
    with patch("app.mfa_web.server.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_auth.login.side_effect = ValueError("unexpected Garmin response shape")
        mock_cls.return_value = mock_auth

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert "Login failed unexpectedly" in response.text


def test_start_needs_mfa_then_verify_succeeds(tmp_path):
    with patch("app.mfa_web.server.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_auth.login.return_value = ("needs_mfa", {"csrf_token": "abc"})
        mock_cls.return_value = mock_auth

        client = _client(tmp_path)
        start_response = client.post("/start")
        assert "multi-factor authentication code" in start_response.text

        verify_response = client.post("/verify", data={"code": "123456"})

    assert verify_response.status_code == 200
    assert "Logged in successfully" in verify_response.text
    mock_auth.resume_login.assert_called_once_with("123456", {"csrf_token": "abc"})
    assert mfa_web_server._pending_auth_client is None
    assert mfa_web_server._pending_mfa_state is None


def test_verify_wraps_auth_error(tmp_path):
    with patch("app.mfa_web.server.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_auth.login.return_value = ("needs_mfa", {"csrf_token": "abc"})
        mock_auth.resume_login.side_effect = AuthError("MFA verification failed")
        mock_cls.return_value = mock_auth

        client = _client(tmp_path)
        client.post("/start")
        verify_response = client.post("/verify", data={"code": "000000"})

    assert verify_response.status_code == 200
    assert "MFA verification failed" in verify_response.text


def test_verify_wraps_transport_error(tmp_path):
    with patch("app.mfa_web.server.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_auth.login.return_value = ("needs_mfa", {"csrf_token": "abc"})
        mock_auth.resume_login.side_effect = requests.exceptions.Timeout("timed out")
        mock_cls.return_value = mock_auth

        client = _client(tmp_path)
        client.post("/start")
        verify_response = client.post("/verify", data={"code": "000000"})

    assert verify_response.status_code == 200
    assert "Could not reach Garmin Connect" in verify_response.text


def test_verify_never_returns_a_raw_500_on_unexpected_error(tmp_path):
    with patch("app.mfa_web.server.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_auth.login.return_value = ("needs_mfa", {"csrf_token": "abc"})
        mock_auth.resume_login.side_effect = ValueError("unexpected Garmin response shape")
        mock_cls.return_value = mock_auth

        client = _client(tmp_path)
        client.post("/start")
        verify_response = client.post("/verify", data={"code": "000000"})

    assert verify_response.status_code == 200
    assert "Verification failed unexpectedly" in verify_response.text


def test_verify_without_pending_flow_shows_error(tmp_path):
    response = _client(tmp_path).post("/verify", data={"code": "123456"})

    assert response.status_code == 200
    assert "No login is currently waiting" in response.text
