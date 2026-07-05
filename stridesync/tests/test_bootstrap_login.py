from unittest.mock import MagicMock, patch

import requests
from garminconnect import GarminConnectAuthenticationError

from app.sync.bootstrap_login import main


def _settings_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_USERNAME", "user@example.com")
    monkeypatch.setenv("GARMIN_PASSWORD", "hunter2")
    monkeypatch.setenv("GARMIN_TOKEN_DIR", str(tmp_path / "tokens"))


def test_missing_credentials_fails_fast(monkeypatch, tmp_path):
    monkeypatch.delenv("GARMIN_USERNAME", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)

    assert main() == 1


def test_login_failure_returns_error(monkeypatch, tmp_path):
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.side_effect = GarminConnectAuthenticationError("bad credentials")
        mock_cls.return_value = mock_garmin

        assert main() == 1


def test_non_mfa_account_logs_in_directly(monkeypatch, tmp_path):
    # Accounts without MFA get a valid session back immediately — no MFA prompt needed.
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = (None, None)
        mock_garmin.client.is_authenticated = True
        mock_cls.return_value = mock_garmin

        assert main() == 0

    mock_garmin.resume_login.assert_not_called()


def test_mfa_account_prompts_and_resumes(monkeypatch, tmp_path):
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.Garmin") as mock_cls, patch(
        "builtins.input", return_value="123456"
    ) as mock_input:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = ("needs_mfa", None)
        mock_garmin.client.is_authenticated = True
        mock_cls.return_value = mock_garmin

        assert main() == 0

    mock_input.assert_called_once()
    mock_garmin.resume_login.assert_called_once_with({}, "123456")


def test_mfa_resume_failure_returns_error(monkeypatch, tmp_path):
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.Garmin") as mock_cls, patch(
        "builtins.input", return_value="000000"
    ):
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = ("needs_mfa", None)
        mock_garmin.resume_login.side_effect = GarminConnectAuthenticationError(
            "MFA verification failed"
        )
        mock_cls.return_value = mock_garmin

        assert main() == 1


def test_login_did_not_produce_a_valid_session_returns_error(monkeypatch, tmp_path):
    # Defensive: login() returns cleanly, but the resulting session is somehow still invalid.
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = (None, None)
        mock_garmin.client.is_authenticated = False
        mock_cls.return_value = mock_garmin

        assert main() == 1


def test_login_transport_error_returns_error(monkeypatch, tmp_path):
    # A raw requests/curl_cffi exception (e.g. a network failure) must not crash uncaught —
    # mirrors garmin_client.py's TRANSPORT_ERRORS handling.
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.side_effect = requests.exceptions.ConnectionError("connection reset")
        mock_cls.return_value = mock_garmin

        assert main() == 1


def test_mfa_resume_transport_error_returns_error(monkeypatch, tmp_path):
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.Garmin") as mock_cls, patch(
        "builtins.input", return_value="000000"
    ):
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = ("needs_mfa", None)
        mock_garmin.resume_login.side_effect = requests.exceptions.ConnectionError("reset")
        mock_cls.return_value = mock_garmin

        assert main() == 1
