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

    @classmethod
    def from_env(cls) -> "Settings":
        """Build Settings from environment variables, matching config.yaml defaults."""
        return cls(
            garmin_username=os.environ.get("GARMIN_USERNAME", ""),
            garmin_password=os.environ.get("GARMIN_PASSWORD", ""),
            sync_interval_hours=_int_env("SYNC_INTERVAL_HOURS", 6),
            mcp_port=_int_env("MCP_PORT", 8765),
            log_level=os.environ.get("LOG_LEVEL", "info"),
            db_path=os.environ.get("STRIDESYNC_DB_PATH", "/data/stridesync.db"),
        )


def _int_env(key: str, default: int) -> int:
    """Read an integer env var, falling back to `default` if unset, empty, or "null".

    `bashio::config` for numeric/port-typed options has been observed to emit the literal
    string "null" (not an empty value) when run standalone without a real HA Supervisor to
    query — int("null") would otherwise crash every service on start with an unhelpful
    ValueError. Treated as "not set" here rather than a fatal error, same as a missing key.
    """
    raw = os.environ.get(key)
    if not raw or raw.strip().lower() == "null":
        return default
    return int(raw)
