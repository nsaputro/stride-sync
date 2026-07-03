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
            sync_interval_hours=int(os.environ.get("SYNC_INTERVAL_HOURS", "6")),
            mcp_port=int(os.environ.get("MCP_PORT", "8765")),
            log_level=os.environ.get("LOG_LEVEL", "info"),
            db_path=os.environ.get("STRIDESYNC_DB_PATH", "/data/stridesync.db"),
        )
