"""SQLite connection + schema management for /data/stridesync.db."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection, creating the schema on first run.

    Args:
        db_path: Path to the SQLite database file (e.g. /data/stridesync.db).

    Returns:
        An open connection with the schema already applied and row access by column name.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the read-only connections used by the web UI and MCP server read while this
    # connection holds a write transaction, instead of hitting "database is locked" — this
    # matters most during backfill, which can hold this connection across hundreds of commits.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't already exist. Safe to call on every startup."""
    conn.executescript(_SCHEMA_PATH.read_text())
    conn.commit()
    _add_column_if_missing(conn, "activity_samples", "temperature_celsius", "REAL")
    _add_column_if_missing(conn, "daily_wellness", "acute_training_load", "REAL")
    _add_column_if_missing(conn, "daily_wellness", "chronic_training_load", "REAL")
    _add_column_if_missing(conn, "daily_wellness", "training_stress_balance", "REAL")
    _add_column_if_missing(conn, "daily_wellness", "acute_chronic_workload_ratio", "REAL")
    _add_column_if_missing(conn, "daily_wellness", "body_battery_charged", "REAL")
    _add_column_if_missing(conn, "daily_wellness", "body_battery_drained", "REAL")
    _add_column_if_missing(conn, "daily_wellness", "stress_avg", "INTEGER")
    _add_column_if_missing(conn, "daily_wellness", "stress_max", "INTEGER")
    _add_column_if_missing(conn, "daily_wellness", "respiration_waking_avg", "REAL")
    _add_column_if_missing(conn, "daily_wellness", "respiration_sleep_avg", "REAL")
    conn.commit()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """Add a column to an already-shipped table if it isn't there yet.

    `CREATE TABLE IF NOT EXISTS` (above) only helps brand-new tables — it's a no-op against a
    database file created by an older version of this schema, so a column added to an existing
    table needs an explicit `ALTER TABLE` here, or every install upgrading from before this
    column existed would start failing every INSERT that includes it.
    """
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
