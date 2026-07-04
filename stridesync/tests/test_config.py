from app.config import Settings


def test_from_env_uses_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("SYNC_INTERVAL_HOURS", raising=False)
    monkeypatch.delenv("MCP_PORT", raising=False)

    settings = Settings.from_env()

    assert settings.sync_interval_hours == 6
    assert settings.mcp_port == 8765


def test_from_env_parses_valid_integers(monkeypatch):
    monkeypatch.setenv("SYNC_INTERVAL_HOURS", "3")
    monkeypatch.setenv("MCP_PORT", "9999")

    settings = Settings.from_env()

    assert settings.sync_interval_hours == 3
    assert settings.mcp_port == 9999


def test_from_env_falls_back_to_default_on_literal_null_string(monkeypatch):
    # bashio::config for schema-validated option types (int ranges, port, list(...) enums) has
    # been observed to emit the literal string "null" when run standalone without a real HA
    # Supervisor — this must not crash Settings.from_env() with a ValueError, it should behave
    # as if the value were unset.
    monkeypatch.setenv("SYNC_INTERVAL_HOURS", "null")
    monkeypatch.setenv("MCP_PORT", "null")
    monkeypatch.setenv("LOG_LEVEL", "null")

    settings = Settings.from_env()

    assert settings.sync_interval_hours == 6
    assert settings.mcp_port == 8765
    assert settings.log_level == "info"


def test_from_env_falls_back_to_default_on_empty_string(monkeypatch):
    monkeypatch.setenv("SYNC_INTERVAL_HOURS", "")
    monkeypatch.setenv("MCP_PORT", "")
    monkeypatch.setenv("LOG_LEVEL", "")

    settings = Settings.from_env()

    assert settings.sync_interval_hours == 6
    assert settings.mcp_port == 8765
    assert settings.log_level == "info"


def test_from_env_parses_valid_log_level(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")

    settings = Settings.from_env()

    assert settings.log_level == "debug"
