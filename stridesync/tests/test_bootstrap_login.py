from unittest.mock import MagicMock, patch

from garmy.core.exceptions import AuthError, LoginError

from app.sync.bootstrap_login import main


def _settings_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_USERNAME", "user@example.com")
    monkeypatch.setenv("GARMIN_PASSWORD", "hunter2")
    monkeypatch.setenv("GARMIN_TOKEN_DIR", str(tmp_path / "tokens"))


def test_missing_credentials_fails_fast(monkeypatch, tmp_path):
    monkeypatch.delenv("GARMIN_USERNAME", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)

    assert main() == 1


def test_already_authenticated_is_a_noop(monkeypatch, tmp_path):
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = True
        mock_cls.return_value = mock_auth

        assert main() == 0

    mock_auth.login.assert_not_called()


def test_login_failure_returns_error(monkeypatch, tmp_path):
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_auth.login.side_effect = LoginError("bad credentials")
        mock_cls.return_value = mock_auth

        assert main() == 1


def test_non_mfa_account_logs_in_directly(monkeypatch, tmp_path):
    # Accounts without MFA get real tokens back immediately — no MFA prompt needed.
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.AuthClient") as mock_cls:
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_auth.login.return_value = (object(), object())
        mock_cls.return_value = mock_auth

        # is_authenticated is checked again after login() to confirm success.
        type(mock_auth).is_authenticated = property(lambda self: True)

        assert main() == 0

    mock_auth.resume_login.assert_not_called()


def test_mfa_account_prompts_and_resumes(monkeypatch, tmp_path):
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.AuthClient") as mock_cls, patch(
        "builtins.input", return_value="123456"
    ) as mock_input:
        mock_auth = MagicMock()
        mfa_state = {"csrf_token": "abc"}

        call_count = {"n": 0}

        def is_authenticated_side_effect(self):
            call_count["n"] += 1
            return call_count["n"] > 1  # False on first check, True after resume_login

        mock_auth.login.return_value = ("needs_mfa", mfa_state)
        mock_cls.return_value = mock_auth
        type(mock_auth).is_authenticated = property(is_authenticated_side_effect)

        assert main() == 0

    mock_input.assert_called_once()
    mock_auth.resume_login.assert_called_once_with("123456", mfa_state)


def test_mfa_resume_failure_returns_error(monkeypatch, tmp_path):
    _settings_env(monkeypatch, tmp_path)

    with patch("app.sync.bootstrap_login.AuthClient") as mock_cls, patch(
        "builtins.input", return_value="000000"
    ):
        mock_auth = MagicMock()
        mock_auth.is_authenticated = False
        mock_auth.login.return_value = ("needs_mfa", {"csrf_token": "abc"})
        mock_auth.resume_login.side_effect = AuthError("MFA verification failed")
        mock_cls.return_value = mock_auth

        assert main() == 1
