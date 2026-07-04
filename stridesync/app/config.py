"""Settings loaded from environment variables.

Each s6 service's `run` script reads `/data/options.json` via `bashio::config` and exports
these as env vars before exec'ing into the Python process (see rootfs/etc/services.d/*/run) —
see PROJECT_PLAN.md §1, HA add-on configuration table. Outside the container (local dev), set
the same env vars directly; see CLAUDE.md, Local Development & Testing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Add-on configuration, mirroring stridesync/config.yaml `options:`."""

    garmin_username: str
    garmin_password: str
    sync_interval_hours: int
    mcp_port: int
    log_level: str
    db_path: str
    garmin_token_dir: str
    mfa_web_port: int

    @classmethod
    def from_env(cls) -> "Settings":
        """Build Settings from environment variables, matching config.yaml defaults."""
        return cls(
            garmin_username=_str_env("GARMIN_USERNAME", ""),
            garmin_password=_str_env("GARMIN_PASSWORD", ""),
            sync_interval_hours=_int_env("SYNC_INTERVAL_HOURS", 6),
            mcp_port=_int_env("MCP_PORT", 8765),
            log_level=_str_env("LOG_LEVEL", "info"),
            db_path=_str_env("STRIDESYNC_DB_PATH", "/data/stridesync.db"),
            garmin_token_dir=_str_env("GARMIN_TOKEN_DIR", "/data/.garmin_tokens"),
            mfa_web_port=_int_env("MFA_WEB_PORT", 8767),
        )


def _str_env(key: str, default: str) -> str:
    """Read a string env var, falling back to `default` if unset, empty, or the literal "null".

    `bashio::config` has been observed to emit the literal string "null" (not an empty value,
    not the schema default) for schema-validated option types — int ranges, `port`, and
    `list(...)` enums — when run standalone without a real HA Supervisor to validate against.
    Plain `str`/`password` options haven't shown this in testing, but treating every field the
    same way here closes the whole class of bug rather than patching it field-by-field as new
    schema types get hit.
    """
    raw = os.environ.get(key)
    if not raw or raw.strip().lower() == "null":
        return default
    return raw


def _int_env(key: str, default: int) -> int:
    """Read an integer env var — see `_str_env` for the "null" fallback this relies on."""
    return int(_str_env(key, str(default)))
