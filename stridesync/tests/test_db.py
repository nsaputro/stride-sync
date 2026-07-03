import sqlite3

from app import db


def test_connect_creates_schema(tmp_path):
    conn = db.connect(str(tmp_path / "stridesync.db"))
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"activities", "activity_metrics", "sync_log"} <= tables
    finally:
        conn.close()


def test_connect_is_idempotent(tmp_path):
    db_path = str(tmp_path / "stridesync.db")
    conn1 = db.connect(db_path)
    conn1.execute(
        "INSERT INTO activities (activity_id, start_time_local, synced_at) VALUES (1, 'x', 'y')"
    )
    conn1.commit()
    conn1.close()

    # Reconnecting must not wipe existing data or fail on "table already exists".
    conn2 = db.connect(db_path)
    try:
        row = conn2.execute("SELECT activity_id FROM activities").fetchone()
        assert row["activity_id"] == 1
    finally:
        conn2.close()


def test_activities_row_factory_allows_column_access(tmp_path):
    conn = db.connect(str(tmp_path / "stridesync.db"))
    try:
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()
