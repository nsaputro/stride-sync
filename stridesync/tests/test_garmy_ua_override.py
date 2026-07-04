import garmy.auth.sso as sso
from garmy.core.config import get_config, reset_config

from app.sync import garmy_ua_override


def _reset(monkeypatch):
    monkeypatch.setattr(garmy_ua_override, "_applied", False)
    reset_config()


def test_apply_sets_default_android_user_agent(monkeypatch):
    monkeypatch.delenv("GARMIN_ANDROID_USER_AGENT", raising=False)
    _reset(monkeypatch)

    garmy_ua_override.apply()

    assert get_config().android_user_agent == garmy_ua_override.DEFAULT_ANDROID_USER_AGENT
    assert sso.USER_AGENT == {"User-Agent": garmy_ua_override.DEFAULT_ANDROID_USER_AGENT}


def test_apply_honors_env_override(monkeypatch):
    monkeypatch.setenv("GARMIN_ANDROID_USER_AGENT", "custom-ua/1.0")
    _reset(monkeypatch)

    garmy_ua_override.apply()

    assert get_config().android_user_agent == "custom-ua/1.0"
    assert sso.USER_AGENT == {"User-Agent": "custom-ua/1.0"}


def test_apply_does_not_disturb_other_config_fields(monkeypatch):
    monkeypatch.delenv("GARMIN_ANDROID_USER_AGENT", raising=False)
    _reset(monkeypatch)
    before = get_config()

    garmy_ua_override.apply()

    after = get_config()
    assert after.request_timeout == before.request_timeout
    assert after.ios_user_agent == before.ios_user_agent


def test_apply_is_idempotent_within_a_process(monkeypatch):
    monkeypatch.setenv("GARMIN_ANDROID_USER_AGENT", "first-ua")
    _reset(monkeypatch)

    garmy_ua_override.apply()
    assert get_config().android_user_agent == "first-ua"

    monkeypatch.setenv("GARMIN_ANDROID_USER_AGENT", "second-ua")
    garmy_ua_override.apply()  # already applied once — must not re-read the env var

    assert get_config().android_user_agent == "first-ua"
