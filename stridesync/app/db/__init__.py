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
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't already exist. Safe to call on every startup."""
    conn.executescript(_SCHEMA_PATH.read_text())
    conn.commit()
