from unittest.mock import MagicMock

from app.sync import mfa_login


def test_start_login_returns_login_result_on_success():
    garmin = MagicMock()
    garmin.login.return_value = (None, None)

    result = mfa_login.start_login(garmin, "/data/.garmin_tokens")

    assert isinstance(result, mfa_login.LoginResult)
    garmin.login.assert_called_once_with(tokenstore="/data/.garmin_tokens")


def test_start_login_returns_needs_mfa_when_library_signals_it():
    garmin = MagicMock()
    garmin.login.return_value = ("needs_mfa", None)

    result = mfa_login.start_login(garmin, "/data/.garmin_tokens")

    assert isinstance(result, mfa_login.NeedsMfa)


def test_resume_login_delegates_to_garmin():
    garmin = MagicMock()

    mfa_login.resume_login(garmin, "123456")

    garmin.resume_login.assert_called_once_with({}, "123456")
