from unittest.mock import MagicMock

from app.sync import mfa_login


def test_start_login_returns_login_result_on_success():
    garmin = MagicMock()
    garmin.login.return_value = (None, None)

    result = mfa_login.start_login(garmin, "/data/.garmin_tokens")

    assert isinstance(result, mfa_login.LoginResult)
    garmin.login.assert_called_once_with(tokenstore="/data/.garmin_tokens")


def test_start_login_persists_session_on_success():
    # Garmin.login() skips its own internal dump() when return_on_mfa=True (required here to
    # detect MFA without an exception) — see mfa_login.py's module docstring. This module must
    # persist the session itself, or a "successful" login is silently never saved.
    garmin = MagicMock()
    garmin.login.return_value = (None, None)

    mfa_login.start_login(garmin, "/data/.garmin_tokens")

    garmin.client.dump.assert_called_once_with("/data/.garmin_tokens")


def test_start_login_does_not_persist_when_no_token_dir():
    garmin = MagicMock()
    garmin.login.return_value = (None, None)

    mfa_login.start_login(garmin, None)

    garmin.client.dump.assert_not_called()


def test_start_login_returns_needs_mfa_when_library_signals_it():
    garmin = MagicMock()
    garmin.login.return_value = ("needs_mfa", None)

    result = mfa_login.start_login(garmin, "/data/.garmin_tokens")

    assert isinstance(result, mfa_login.NeedsMfa)


def test_start_login_does_not_persist_when_mfa_still_pending():
    garmin = MagicMock()
    garmin.login.return_value = ("needs_mfa", None)

    mfa_login.start_login(garmin, "/data/.garmin_tokens")

    garmin.client.dump.assert_not_called()


def test_resume_login_delegates_to_garmin():
    garmin = MagicMock()

    mfa_login.resume_login(garmin, "123456", "/data/.garmin_tokens")

    garmin.resume_login.assert_called_once_with({}, "123456")


def test_resume_login_persists_session():
    garmin = MagicMock()

    mfa_login.resume_login(garmin, "123456", "/data/.garmin_tokens")

    garmin.client.dump.assert_called_once_with("/data/.garmin_tokens")


def test_resume_login_does_not_persist_when_no_token_dir():
    garmin = MagicMock()

    mfa_login.resume_login(garmin, "123456", None)

    garmin.client.dump.assert_not_called()
