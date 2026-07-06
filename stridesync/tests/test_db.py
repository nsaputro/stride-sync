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
        assert {
            "activities", "activity_metrics", "sync_log", "daily_wellness", "vo2max_history"
        } <= tables
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


def test_connect_enables_wal_mode(tmp_path):
    conn = db.connect(str(tmp_path / "stridesync.db"))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_connect_sets_busy_timeout(tmp_path):
    conn = db.connect(str(tmp_path / "stridesync.db"))
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()


def test_connect_adds_temperature_column_to_an_older_database(tmp_path):
    # Simulates an install that shipped before temperature_celsius existed: CREATE TABLE IF NOT
    # EXISTS (in schema.sql) is a no-op against an already-existing table, so upgrading needs an
    # explicit migration step, or every sync afterward would fail inserting into this column.
    db_path = str(tmp_path / "stridesync.db")
    old_conn = sqlite3.connect(db_path)
    old_conn.execute(
        """
        CREATE TABLE activity_samples (
            activity_id INTEGER NOT NULL,
            sample_index INTEGER NOT NULL,
            heart_rate INTEGER,
            PRIMARY KEY (activity_id, sample_index)
        )
        """
    )
    old_conn.execute(
        "INSERT INTO activity_samples (activity_id, sample_index, heart_rate) VALUES (1, 0, 150)"
    )
    old_conn.commit()
    old_conn.close()

    conn = db.connect(db_path)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_samples)")}
        assert "temperature_celsius" in columns
        # Pre-existing data must survive the migration untouched.
        row = conn.execute("SELECT heart_rate FROM activity_samples WHERE activity_id = 1").fetchone()
        assert row["heart_rate"] == 150
    finally:
        conn.close()


def test_readonly_reader_does_not_block_writer_in_wal_mode(tmp_path):
    """A read-only connection must not stop the write connection from committing.

    Regression test for a real bug: the backfill feature holds a single write connection open
    across hundreds of commits, and a web UI read landing mid-write raised
    sqlite3.OperationalError ("database is locked") before WAL mode was enabled — in WAL mode,
    readers and the one writer never block each other.
    """
    db_path = str(tmp_path / "stridesync.db")
    writer = db.connect(db_path)

    reader = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    reader.execute("PRAGMA busy_timeout = 5000")
    try:
        # Hold the reader's transaction open (a snapshot) while the writer commits — this is
        # exactly the WAL guarantee that a rollback-journal DB doesn't provide.
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM activities").fetchone()

        writer.execute(
            "INSERT INTO activities (activity_id, start_time_local, synced_at) "
            "VALUES (1, 'x', 'y')"
        )
        writer.commit()

        assert reader.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0
    finally:
        reader.close()
        writer.close()
