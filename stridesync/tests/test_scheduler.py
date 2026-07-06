import signal
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.sync.garmin_client import (
    ActivitySample,
    DailyWellness,
    GarminActivity,
    GarminAPIError,
    GarminAuthError,
    GarminLap,
    HrZoneTime,
    TrainingBaseline,
    Vo2MaxReading,
)
from app.sync.scheduler import (
    _install_shutdown_handler,
    run_backfill_sync,
    run_forever,
    run_sync_once,
)


def make_settings(tmp_path) -> Settings:
    return Settings(
        garmin_username="user@example.com",
        garmin_password="hunter2",
        sync_interval_hours=6,
        mcp_port=8765,
        log_level="info",
        db_path=str(tmp_path / "stridesync.db"),
        garmin_token_dir=str(tmp_path / "garmin_tokens"),
        mfa_web_port=8767,
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


def make_training_baseline() -> TrainingBaseline:
    return TrainingBaseline(
        lactate_threshold_hr=165,
        lactate_threshold_speed_mps=3.2,
        lactate_threshold_pace_sec_per_km=312.5,
        race_prediction_5k_seconds=1200,
        race_prediction_10k_seconds=2500,
        race_prediction_half_marathon_seconds=5600,
        race_prediction_marathon_seconds=11800,
    )


def make_daily_wellness(calendar_date="2026-07-06") -> DailyWellness:
    return DailyWellness(
        calendar_date=calendar_date,
        sleep_score=82,
        sleep_duration_seconds=27000.0,
        deep_sleep_seconds=5400.0,
        light_sleep_seconds=14400.0,
        rem_sleep_seconds=6300.0,
        awake_sleep_seconds=900.0,
        hrv_status="BALANCED",
        hrv_weekly_avg_ms=55.0,
        hrv_last_night_avg_ms=53.0,
        training_status_label="PRODUCTIVE",
        training_readiness_score=78,
        resting_hr=48,
    )


def make_vo2max_reading(calendar_date="2026-07-06") -> Vo2MaxReading:
    return Vo2MaxReading(
        calendar_date=calendar_date,
        vo2_max_running=52.5,
        vo2_max_cycling=48.0,
        fitness_age=28,
    )


def make_hr_zone(activity_id=1, zone_number=2) -> HrZoneTime:
    return HrZoneTime(
        activity_id=activity_id,
        zone_number=zone_number,
        zone_low_boundary_hr=140,
        seconds_in_zone=900.0,
    )


def make_sample(activity_id=1, sample_index=0) -> ActivitySample:
    return ActivitySample(
        activity_id=activity_id,
        sample_index=sample_index,
        elapsed_seconds=10.0,
        heart_rate=150,
        speed_mps=2.78,
        pace_sec_per_km=359.7,
        cadence_spm=170.0,
        elevation_meters=12.5,
        latitude=37.0,
        longitude=-122.0,
        temperature_celsius=18.0,
    )


class FakeGarminClient:
    def __init__(
        self,
        activities=None,
        laps=None,
        login_error=None,
        fetch_error=None,
        baseline=None,
        hr_zones=None,
        samples=None,
        since_activities=None,
        since_error=None,
        wellness=None,
        vo2max=None,
    ):
        self._activities = activities or []
        self._laps = laps or {}
        self._login_error = login_error
        self._fetch_error = fetch_error
        self._baseline = baseline
        self._hr_zones = hr_zones or {}
        self._samples = samples or {}
        self._since_activities = since_activities if since_activities is not None else activities or []
        self._since_error = since_error
        self._wellness = wellness or {}
        self._vo2max = vo2max or {}
        self.login_called = False
        self.since_start_date = None

    def login(self):
        self.login_called = True
        if self._login_error:
            raise self._login_error

    def fetch_recent_activities(self, limit=20):
        if self._fetch_error:
            raise self._fetch_error
        return self._activities

    def fetch_activities_since(self, start_date):
        self.since_start_date = start_date
        if self._since_error:
            raise self._since_error
        return self._since_activities

    def fetch_activity_laps(self, activity_id):
        return self._laps.get(activity_id, [])

    def fetch_training_baseline(self):
        return self._baseline

    def fetch_activity_hr_zones(self, activity_id):
        return self._hr_zones.get(activity_id, [])

    def fetch_activity_samples(self, activity_id):
        return self._samples.get(activity_id, [])

    def fetch_daily_wellness(self, cdate):
        # Real GarminClient.fetch_daily_wellness never returns None (calendar_date is always
        # known) -- mirror that contract for unconfigured dates instead of returning None.
        return self._wellness.get(
            cdate,
            DailyWellness(
                calendar_date=cdate,
                sleep_score=None,
                sleep_duration_seconds=None,
                deep_sleep_seconds=None,
                light_sleep_seconds=None,
                rem_sleep_seconds=None,
                awake_sleep_seconds=None,
                hrv_status=None,
                hrv_weekly_avg_ms=None,
                hrv_last_night_avg_ms=None,
                training_status_label=None,
                training_readiness_score=None,
                resting_hr=None,
            ),
        )

    def fetch_vo2max(self, cdate):
        # Real GarminClient.fetch_vo2max returns None when unavailable (matches
        # fetch_training_baseline's contract) -- mirror that for unconfigured dates.
        return self._vo2max.get(cdate)


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


def test_run_sync_once_writes_training_baseline(tmp_path):
    settings = make_settings(tmp_path)
    baseline = make_training_baseline()
    client = FakeGarminClient(activities=[make_activity()], baseline=baseline)

    run_sync_once(settings, client)

    from app import db

    conn = db.connect(settings.db_path)
    try:
        row = conn.execute("SELECT * FROM training_baseline WHERE id = 1").fetchone()
        assert row["lactate_threshold_hr"] == 165
        assert row["race_prediction_marathon_seconds"] == 11800
    finally:
        conn.close()


def test_run_sync_once_skips_training_baseline_when_unavailable(tmp_path):
    # See GarminClient.fetch_training_baseline's docstring: not every account has this data, and
    # that must not be treated as an error -- just nothing to store.
    settings = make_settings(tmp_path)
    client = FakeGarminClient(activities=[make_activity()], baseline=None)

    run_sync_once(settings, client)

    from app import db

    conn = db.connect(settings.db_path)
    try:
        row = conn.execute("SELECT * FROM training_baseline WHERE id = 1").fetchone()
        assert row is None
    finally:
        conn.close()


def test_run_sync_once_writes_daily_wellness(tmp_path):
    settings = make_settings(tmp_path)
    today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()
    yesterday_str = (today - timedelta(days=1)).isoformat()
    client = FakeGarminClient(
        activities=[make_activity()],
        wellness={
            today_str: make_daily_wellness(today_str),
            yesterday_str: make_daily_wellness(yesterday_str),
        },
    )

    run_sync_once(settings, client)

    from app import db

    conn = db.connect(settings.db_path)
    try:
        today_row = conn.execute(
            "SELECT * FROM daily_wellness WHERE calendar_date = ?", (today_str,)
        ).fetchone()
        yesterday_row = conn.execute(
            "SELECT * FROM daily_wellness WHERE calendar_date = ?", (yesterday_str,)
        ).fetchone()
        assert today_row["sleep_score"] == 82
        assert today_row["resting_hr"] == 48
        assert yesterday_row["hrv_status"] == "BALANCED"
    finally:
        conn.close()


def test_run_sync_once_upserts_daily_wellness_rather_than_duplicating(tmp_path):
    settings = make_settings(tmp_path)
    today_str = datetime.now(timezone.utc).date().isoformat()
    first_run_wellness = make_daily_wellness(today_str)
    client1 = FakeGarminClient(
        activities=[make_activity()], wellness={today_str: first_run_wellness}
    )
    run_sync_once(settings, client1)

    updated_wellness = DailyWellness(**{**first_run_wellness.__dict__, "sleep_score": 55})
    client2 = FakeGarminClient(
        activities=[make_activity()], wellness={today_str: updated_wellness}
    )
    run_sync_once(settings, client2)

    from app import db

    conn = db.connect(settings.db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM daily_wellness WHERE calendar_date = ?", (today_str,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["sleep_score"] == 55
    finally:
        conn.close()


def test_run_sync_once_writes_vo2max_history(tmp_path):
    settings = make_settings(tmp_path)
    today_str = datetime.now(timezone.utc).date().isoformat()
    yesterday_str = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    # Only configure vo2max for one of the window's dates -- proves fetch_vo2max returning None
    # for the other dates is a no-op, not an error or a row of nulls.
    client = FakeGarminClient(
        activities=[make_activity()], vo2max={today_str: make_vo2max_reading(today_str)}
    )

    run_sync_once(settings, client)

    from app import db

    conn = db.connect(settings.db_path)
    try:
        rows = conn.execute("SELECT * FROM vo2max_history").fetchall()
        assert len(rows) == 1
        assert rows[0]["calendar_date"] == today_str
        assert rows[0]["vo2_max_running"] == 52.5
        assert rows[0]["fitness_age"] == 28
        assert (
            conn.execute(
                "SELECT * FROM vo2max_history WHERE calendar_date = ?", (yesterday_str,)
            ).fetchone()
            is None
        )
    finally:
        conn.close()


def test_run_sync_once_writes_hr_zones_and_samples(tmp_path):
    settings = make_settings(tmp_path)
    zone = make_hr_zone()
    sample = make_sample()
    client = FakeGarminClient(
        activities=[make_activity()],
        hr_zones={1: [zone]},
        samples={1: [sample]},
    )

    run_sync_once(settings, client)

    from app import db

    conn = db.connect(settings.db_path)
    try:
        zone_row = conn.execute(
            "SELECT * FROM activity_hr_zones WHERE activity_id = 1 AND zone_number = 2"
        ).fetchone()
        assert zone_row["seconds_in_zone"] == 900.0

        sample_row = conn.execute(
            "SELECT * FROM activity_samples WHERE activity_id = 1 AND sample_index = 0"
        ).fetchone()
        assert sample_row["heart_rate"] == 150
        assert sample_row["pace_sec_per_km"] == 359.7
        assert sample_row["temperature_celsius"] == 18.0
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


def test_run_backfill_sync_writes_activities(tmp_path):
    settings = make_settings(tmp_path)
    activity = make_activity()
    lap = make_lap()
    client = FakeGarminClient(since_activities=[activity], laps={1: [lap]})

    count = run_backfill_sync(settings, client, "2020-01-01")

    assert count == 1
    assert client.login_called
    assert client.since_start_date == "2020-01-01"

    from app import db

    conn = db.connect(settings.db_path)
    try:
        row = conn.execute("SELECT * FROM activities WHERE activity_id = 1").fetchone()
        assert row["activity_name"] == "Morning Run"

        log_row = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        assert log_row["status"] == "success"
        assert log_row["activities_synced"] == 1
    finally:
        conn.close()


def test_run_backfill_sync_reports_progress(tmp_path):
    settings = make_settings(tmp_path)
    activities = [make_activity(1), make_activity(2)]
    client = FakeGarminClient(since_activities=activities)
    calls = []

    run_backfill_sync(settings, client, "2020-01-01", progress_callback=lambda c, t: calls.append((c, t)))

    # Called once up front with the known total (before any activity is processed), then once
    # per completed activity.
    assert calls == [(0, 2), (1, 2), (2, 2)]


def test_run_backfill_sync_does_not_touch_training_baseline(tmp_path):
    # Backfill is about historical activities, not the athlete's current physiological
    # baseline -- that stays the regular scheduled sync's job (run_sync_once).
    settings = make_settings(tmp_path)
    client = FakeGarminClient(since_activities=[make_activity()])

    run_backfill_sync(settings, client, "2020-01-01")

    from app import db

    conn = db.connect(settings.db_path)
    try:
        assert conn.execute("SELECT * FROM training_baseline").fetchone() is None
    finally:
        conn.close()


def test_run_backfill_sync_does_not_touch_daily_wellness(tmp_path):
    # Same rationale as training_baseline above -- daily_wellness stays run_sync_once's job.
    settings = make_settings(tmp_path)
    client = FakeGarminClient(since_activities=[make_activity()])

    run_backfill_sync(settings, client, "2020-01-01")

    from app import db

    conn = db.connect(settings.db_path)
    try:
        assert conn.execute("SELECT * FROM daily_wellness").fetchone() is None
    finally:
        conn.close()


def test_run_backfill_sync_does_not_touch_vo2max_history(tmp_path):
    # Same rationale as training_baseline/daily_wellness above.
    settings = make_settings(tmp_path)
    client = FakeGarminClient(since_activities=[make_activity()])

    run_backfill_sync(settings, client, "2020-01-01")

    from app import db

    conn = db.connect(settings.db_path)
    try:
        assert conn.execute("SELECT * FROM vo2max_history").fetchone() is None
    finally:
        conn.close()


def test_run_backfill_sync_logs_failure_on_auth_error(tmp_path):
    settings = make_settings(tmp_path)
    client = FakeGarminClient(login_error=GarminAuthError("bad credentials"))

    with pytest.raises(GarminAuthError):
        run_backfill_sync(settings, client, "2020-01-01")

    from app import db

    conn = db.connect(settings.db_path)
    try:
        log_row = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        assert log_row["status"] == "failed"
        assert "bad credentials" in log_row["error_message"]
        assert log_row["activities_synced"] == 0
    finally:
        conn.close()


def test_run_backfill_sync_logs_failure_on_fetch_error(tmp_path):
    settings = make_settings(tmp_path)
    client = FakeGarminClient(since_error=GarminAPIError("garmin is down"))

    with pytest.raises(GarminAPIError):
        run_backfill_sync(settings, client, "2020-01-01")

    from app import db

    conn = db.connect(settings.db_path)
    try:
        log_row = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        assert log_row["status"] == "failed"
        assert "Backfill since 2020-01-01 failed" in log_row["error_message"]
        assert "garmin is down" in log_row["error_message"]
    finally:
        conn.close()


def test_run_backfill_sync_propagates_bad_date_without_logging(tmp_path):
    # A bad start_date is a caller-input error, not a sync attempt -- see
    # run_backfill_sync's docstring: nothing gets written or logged for this case.
    settings = make_settings(tmp_path)
    client = FakeGarminClient(since_error=ValueError("startdate must be in format 'YYYY-MM-DD'"))

    with pytest.raises(ValueError):
        run_backfill_sync(settings, client, "not-a-date")

    from app import db

    conn = db.connect(settings.db_path)
    try:
        assert conn.execute("SELECT * FROM sync_log").fetchone() is None
    finally:
        conn.close()


class TestRunForever:
    def test_stops_after_max_iterations_without_waiting_full_interval(self, tmp_path):
        settings = make_settings(tmp_path)
        activity = make_activity()
        made_clients = []

        def make_client():
            client = FakeGarminClient(activities=[activity])
            made_clients.append(client)
            return client

        # interval_seconds=0 keeps the test instant even though sync_interval_hours is 6.
        run_forever(settings, make_client, interval_seconds=0, max_iterations=3)

        assert len(made_clients) == 3
        assert all(c.login_called for c in made_clients)

        from app import db

        conn = db.connect(settings.db_path)
        try:
            rows = conn.execute("SELECT * FROM sync_log").fetchall()
            assert len(rows) == 3
            assert all(r["status"] == "success" for r in rows)
        finally:
            conn.close()

    def test_stop_event_ends_the_loop_promptly(self, tmp_path):
        # A long interval (1 hour) proves stop_event short-circuits the wait instead of the
        # loop actually waiting it out. A background timer sets stop_event from a separate
        # thread — setting it from inside make_client would deadlock, since the *next* call to
        # make_client only happens after the current wait() returns.
        settings = make_settings(tmp_path)
        stop_event = threading.Event()
        calls = []

        def make_client():
            calls.append(1)
            return FakeGarminClient(activities=[make_activity()])

        timer = threading.Timer(0.05, stop_event.set)
        timer.start()
        try:
            start = time.monotonic()
            run_forever(settings, make_client, interval_seconds=3600, stop_event=stop_event)
            elapsed = time.monotonic() - start
        finally:
            timer.cancel()

        assert elapsed < 5, "stop_event should short-circuit the 3600s wait, not run it out"
        assert len(calls) == 1

    def test_auth_failure_does_not_crash_the_loop(self, tmp_path):
        # CLAUDE.md: sync failures must never crash the service — the sync-scheduler must keep
        # retrying on the next interval rather than taking the whole s6 service down.
        settings = make_settings(tmp_path)
        attempts = []

        def make_client():
            attempts.append(1)
            return FakeGarminClient(login_error=GarminAuthError("SSO login flow broke"))

        run_forever(settings, make_client, interval_seconds=0, max_iterations=3)

        assert len(attempts) == 3

        from app import db

        conn = db.connect(settings.db_path)
        try:
            rows = conn.execute("SELECT * FROM sync_log ORDER BY id").fetchall()
            assert len(rows) == 3
            assert all(r["status"] == "failed" for r in rows)
            assert all("SSO login flow broke" in r["error_message"] for r in rows)
        finally:
            conn.close()

    def test_defaults_interval_from_settings_sync_interval_hours(self, tmp_path):
        settings = make_settings(tmp_path)  # sync_interval_hours=6
        stop_event = threading.Event()
        stop_event.set()  # loop should check this before ever computing a real 6h wait

        recorded_timeouts = []
        real_wait = threading.Event.wait

        def spying_wait(self, timeout=None):
            recorded_timeouts.append(timeout)
            return real_wait(self, timeout)

        threading.Event.wait = spying_wait
        try:
            run_forever(
                settings,
                lambda: FakeGarminClient(activities=[make_activity()]),
                stop_event=stop_event,
            )
        finally:
            threading.Event.wait = real_wait

        assert recorded_timeouts == [6 * 3600]


class TestInstallShutdownHandler:
    def test_sigterm_sets_stop_event(self):
        stop_event = threading.Event()
        original = signal.getsignal(signal.SIGTERM)
        try:
            _install_shutdown_handler(stop_event)
            handler = signal.getsignal(signal.SIGTERM)
            handler(signal.SIGTERM, None)
            assert stop_event.is_set()
        finally:
            signal.signal(signal.SIGTERM, original)
