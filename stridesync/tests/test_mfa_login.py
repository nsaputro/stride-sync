from unittest.mock import MagicMock

from app.sync import mfa_login


def test_start_login_returns_already_authenticated_without_calling_login():
    auth_client = MagicMock()
    auth_client.is_authenticated = True

    result = mfa_login.start_login(auth_client, "user@example.com", "hunter2")

    assert isinstance(result, mfa_login.LoginResult)
    assert result.already_authenticated is True
    auth_client.login.assert_not_called()


def test_start_login_returns_login_result_on_direct_success():
    auth_client = MagicMock()
    auth_client.is_authenticated = False
    auth_client.login.return_value = (object(), object())

    result = mfa_login.start_login(auth_client, "user@example.com", "hunter2")

    assert isinstance(result, mfa_login.LoginResult)
    assert result.already_authenticated is False
    auth_client.login.assert_called_once_with(
        "user@example.com", "hunter2", return_on_mfa=True
    )


def test_start_login_returns_needs_mfa_on_mfa_tuple():
    auth_client = MagicMock()
    auth_client.is_authenticated = False
    mfa_state = {"csrf_token": "abc"}
    auth_client.login.return_value = ("needs_mfa", mfa_state)

    result = mfa_login.start_login(auth_client, "user@example.com", "hunter2")

    assert isinstance(result, mfa_login.NeedsMfa)
    assert result.mfa_state is mfa_state


def test_resume_login_delegates_to_auth_client():
    auth_client = MagicMock()
    mfa_state = {"csrf_token": "abc"}

    mfa_login.resume_login(auth_client, "123456", mfa_state)

    auth_client.resume_login.assert_called_once_with("123456", mfa_state)
