import pytest

from app.config import Settings
from app.sync.garmin_client import GarminActivity, GarminAPIError, GarminAuthError, GarminLap
from app.sync.scheduler import run_sync_once


def make_settings(tmp_path) -> Settings:
    return Settings(
        garmin_username="user@example.com",
        garmin_password="hunter2",
        sync_interval_hours=6,
        mcp_port=8765,
        log_level="info",
        db_path=str(tmp_path / "stridesync.db"),
    )


def make_activity(activity_id=1) -> GarminActivity:
    return GarminActivity(
        activity_id=activity_id,
        activity_name="Morning Run",
        activity_type="running",
        start_time_local="2026-06-01 06:30:00",
        start_time_gmt="2026-06-01 13:30:00",
        duration_seconds=1800.0,
        moving_duration_seconds=1750.0,
        distance_meters=5000.0,
        average_speed_mps=2.78,
        average_pace_sec_per_km=359.7,
        average_hr=150,
        max_hr=172,
        average_cadence_spm=170.0,
        max_cadence_spm=182.0,
        elevation_gain_meters=45.0,
        elevation_loss_meters=40.0,
        calories=320.0,
        aerobic_training_effect=3.2,
        anaerobic_training_effect=0.5,
        training_effect_label="TEMPO",
        activity_training_load=85.0,
    )


def make_lap(activity_id=1, lap_index=0) -> GarminLap:
    return GarminLap(
        activity_id=activity_id,
        lap_index=lap_index,
        start_time_gmt="2026-06-01 13:30:00",
        duration_seconds=300.0,
        distance_meters=1000.0,
        average_speed_mps=3.0,
        pace_sec_per_km=333.3,
        average_hr=148,
        max_hr=160,
        average_cadence_spm=172.0,
        max_cadence_spm=178.0,
    )


class FakeGarminClient:
    def __init__(self, activities=None, laps=None, login_error=None, fetch_error=None):
        self._activities = activities or []
        self._laps = laps or {}
        self._login_error = login_error
        self._fetch_error = fetch_error
        self.login_called = False

    def login(self):
        self.login_called = True
        if self._login_error:
            raise self._login_error

    def fetch_recent_activities(self, limit=20):
        if self._fetch_error:
            raise self._fetch_error
        return self._activities

    def fetch_activity_laps(self, activity_id):
        return self._laps.get(activity_id, [])


def test_run_sync_once_writes_activities_and_laps(tmp_path):
    settings = make_settings(tmp_path)
    activity = make_activity()
    lap = make_lap()
    client = FakeGarminClient(activities=[activity], laps={1: [lap]})

    count = run_sync_once(settings, client)

    assert count == 1
    assert client.login_called

    from app import db

    conn = db.connect(settings.db_path)
    try:
        row = conn.execute("SELECT * FROM activities WHERE activity_id = 1").fetchone()
        assert row["activity_name"] == "Morning Run"
        assert row["distance_meters"] == 5000.0

        lap_row = conn.execute(
            "SELECT * FROM activity_metrics WHERE activity_id = 1 AND lap_index = 0"
        ).fetchone()
        assert lap_row["distance_meters"] == 1000.0

        log_row = conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert log_row["status"] == "success"
        assert log_row["activities_synced"] == 1
    finally:
        conn.close()


def test_run_sync_once_upserts_existing_activity(tmp_path):
    settings = make_settings(tmp_path)
    client = FakeGarminClient(activities=[make_activity()])
    run_sync_once(settings, client)

    updated = make_activity()
    updated = updated.__class__(**{**updated.__dict__, "activity_name": "Evening Run"})
    client2 = FakeGarminClient(activities=[updated])
    run_sync_once(settings, client2)

    from app import db

    conn = db.connect(settings.db_path)
    try:
        rows = conn.execute("SELECT * FROM activities").fetchall()
        assert len(rows) == 1
        assert rows[0]["activity_name"] == "Evening Run"
    finally:
        conn.close()


def test_run_sync_once_logs_failure_on_auth_error(tmp_path):
    settings = make_settings(tmp_path)
    client = FakeGarminClient(login_error=GarminAuthError("bad credentials"))

    with pytest.raises(GarminAuthError):
        run_sync_once(settings, client)

    from app import db

    conn = db.connect(settings.db_path)
    try:
        log_row = conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert log_row["status"] == "failed"
        assert "bad credentials" in log_row["error_message"]
        assert log_row["activities_synced"] == 0
    finally:
        conn.close()


def test_run_sync_once_logs_failure_on_fetch_error(tmp_path):
    settings = make_settings(tmp_path)
    client = FakeGarminClient(fetch_error=GarminAPIError("garmin is down"))

    with pytest.raises(GarminAPIError):
        run_sync_once(settings, client)

    from app import db

    conn = db.connect(settings.db_path)
    try:
        log_row = conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert log_row["status"] == "failed"
        assert "garmin is down" in log_row["error_message"]
    finally:
        conn.close()
