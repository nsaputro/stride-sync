from unittest.mock import MagicMock, patch

import garmy.auth.sso as sso

from app.sync import garmy_login_delay


def _reset(monkeypatch):
    monkeypatch.setattr(garmy_login_delay, "_applied", False)
    monkeypatch.setattr(sso, "_perform_initial_login", sso._perform_initial_login)


def test_apply_delays_before_calling_the_original_perform_initial_login(monkeypatch):
    monkeypatch.delenv("GARMIN_LOGIN_DELAY_MIN_S", raising=False)
    monkeypatch.delenv("GARMIN_LOGIN_DELAY_MAX_S", raising=False)
    _reset(monkeypatch)

    original = MagicMock(return_value="Success")
    monkeypatch.setattr(sso, "_perform_initial_login", original)

    with patch("app.sync.garmy_login_delay.time.sleep") as mock_sleep, patch(
        "app.sync.garmy_login_delay.random.uniform", return_value=5.0
    ) as mock_uniform:
        garmy_login_delay.apply()

        result = sso._perform_initial_login("auth_client", "user", "pw", "csrf", "params")

    mock_uniform.assert_called_once_with(
        garmy_login_delay.DEFAULT_MIN_DELAY_SECONDS, garmy_login_delay.DEFAULT_MAX_DELAY_SECONDS
    )
    mock_sleep.assert_called_once_with(5.0)
    original.assert_called_once_with("auth_client", "user", "pw", "csrf", "params")
    assert result == "Success"


def test_apply_honors_env_override(monkeypatch):
    monkeypatch.setenv("GARMIN_LOGIN_DELAY_MIN_S", "1.5")
    monkeypatch.setenv("GARMIN_LOGIN_DELAY_MAX_S", "2.5")
    _reset(monkeypatch)

    monkeypatch.setattr(sso, "_perform_initial_login", MagicMock(return_value="Success"))

    with patch("app.sync.garmy_login_delay.time.sleep"), patch(
        "app.sync.garmy_login_delay.random.uniform", return_value=2.0
    ) as mock_uniform:
        garmy_login_delay.apply()
        sso._perform_initial_login("a", "b", "c", "d", "e")

    mock_uniform.assert_called_once_with(1.5, 2.5)


def test_apply_is_idempotent(monkeypatch):
    _reset(monkeypatch)

    garmy_login_delay.apply()
    patched = sso._perform_initial_login

    garmy_login_delay.apply()

    assert sso._perform_initial_login is patched
