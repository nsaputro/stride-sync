from unittest.mock import MagicMock, patch

import pytest
import requests
from starlette.testclient import TestClient

from app.mfa_web import server as mfa_web_server
from app.config import Settings
from garminconnect import GarminConnectAuthenticationError


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


@pytest.fixture(autouse=True)
def _reset_pending_state():
    # mfa_web.server keeps one in-process pending-login slot (see its module docstring) —
    # reset it around every test so state can't leak between them.
    mfa_web_server._pending_garmin = None
    yield
    mfa_web_server._pending_garmin = None


def _client(tmp_path) -> TestClient:
    app = mfa_web_server.create_app(make_settings(tmp_path))
    return TestClient(app)


def test_index_shows_not_logged_in_when_no_session(tmp_path):
    response = _client(tmp_path).get("/")

    assert response.status_code == 200
    assert "No valid Garmin Connect session" in response.text
    assert 'action="sync"' not in response.text


def test_index_shows_logged_in_when_session_cached(tmp_path):
    token_dir = tmp_path / "garmin_tokens"
    token_dir.mkdir()
    (token_dir / "garmin_tokens.json").write_text("{}")

    response = _client(tmp_path).get("/")

    assert response.status_code == 200
    assert "Already logged in" in response.text
    assert 'action="sync"' in response.text


def test_index_shows_no_sync_yet_when_db_missing(tmp_path):
    response = _client(tmp_path).get("/")

    assert response.status_code == 200
    assert "Total activities synced: 0" in response.text
    assert "No sync has run yet" in response.text


def test_index_shows_total_activities_and_last_sync_success(tmp_path):
    from app import db

    settings = make_settings(tmp_path)
    conn = db.connect(settings.db_path)
    for activity_id in (1, 2, 3):
        conn.execute(
            "INSERT INTO activities (activity_id, start_time_local, synced_at) VALUES (?, ?, ?)",
            (activity_id, "2026-07-01 06:00:00", "2026-07-01T06:05:00"),
        )
    conn.execute(
        """
        INSERT INTO sync_log (started_at, finished_at, status, activities_synced, error_message)
        VALUES (?, ?, 'success', 3, NULL)
        """,
        ("2026-07-01T06:00:00", "2026-07-01T06:05:00"),
    )
    conn.commit()
    conn.close()

    response = TestClient(mfa_web_server.create_app(settings)).get("/")

    assert response.status_code == 200
    assert "Total activities synced: 3" in response.text
    assert "Last sync: success at 2026-07-01 06:05 UTC (3 activities)" in response.text


def test_index_shows_last_sync_error(tmp_path):
    from app import db

    settings = make_settings(tmp_path)
    conn = db.connect(settings.db_path)
    conn.execute(
        """
        INSERT INTO sync_log (started_at, finished_at, status, activities_synced, error_message)
        VALUES (?, ?, 'failed', 0, ?)
        """,
        ("2026-07-01T06:00:00", "2026-07-01T06:00:05", "Could not reach Garmin Connect"),
    )
    conn.commit()
    conn.close()

    response = TestClient(mfa_web_server.create_app(settings)).get("/")

    assert response.status_code == 200
    assert "Last sync: failed at 2026-07-01 06:00 UTC (0 activities)" in response.text
    assert "Last sync error: Could not reach Garmin Connect" in response.text


def test_index_shows_no_recent_activities_section_when_none_synced(tmp_path):
    response = _client(tmp_path).get("/")

    assert response.status_code == 200
    assert "Recent activities" not in response.text


def test_index_shows_recent_activities_with_distance_and_timestamp(tmp_path):
    from app import db

    settings = make_settings(tmp_path)
    conn = db.connect(settings.db_path)
    conn.execute(
        """
        INSERT INTO activities (
            activity_id, activity_name, activity_type, start_time_local, start_time_gmt,
            distance_meters, synced_at
        ) VALUES (1, 'Morning Run', 'running', '2026-07-01 06:30:00', '2026-07-01 13:30:00',
                  5000.0, datetime('now'))
        """
    )
    conn.execute(
        """
        INSERT INTO activities (
            activity_id, activity_name, activity_type, start_time_local, start_time_gmt,
            distance_meters, synced_at
        ) VALUES (2, 'Evening Jog', 'running', '2026-06-30 18:00:00', '2026-06-30 01:00:00',
                  3200.0, datetime('now'))
        """
    )
    conn.commit()
    conn.close()

    response = TestClient(mfa_web_server.create_app(settings)).get("/")

    assert response.status_code == 200
    assert "Recent activities" in response.text
    assert "Morning Run" in response.text
    assert "2026-07-01 06:30" in response.text
    assert "5.00 km" in response.text
    assert "Evening Jog" in response.text
    assert "3.20 km" in response.text
    # newest first
    assert response.text.index("Morning Run") < response.text.index("Evening Jog")


def test_index_recent_activities_falls_back_to_activity_type_when_name_missing(tmp_path):
    from app import db

    settings = make_settings(tmp_path)
    conn = db.connect(settings.db_path)
    conn.execute(
        """
        INSERT INTO activities (
            activity_id, activity_name, activity_type, start_time_local, start_time_gmt,
            distance_meters, synced_at
        ) VALUES (1, NULL, 'running', '2026-07-01 06:30:00', '2026-07-01 13:30:00', NULL,
                  datetime('now'))
        """
    )
    conn.commit()
    conn.close()

    response = TestClient(mfa_web_server.create_app(settings)).get("/")

    assert response.status_code == 200
    assert "running" in response.text
    assert "—" in response.text  # missing distance shown as an em dash, not a crash


def test_index_shows_nav_with_dashboard_active(tmp_path):
    response = _client(tmp_path).get("/")

    assert response.status_code == 200
    assert '<nav class="tabs">' in response.text
    assert 'href="." class="active"' in response.text
    assert 'href="running"' in response.text


def test_running_page_shows_nav_with_running_active(tmp_path):
    response = _client(tmp_path).get("/running")

    assert response.status_code == 200
    assert '<nav class="tabs">' in response.text
    assert 'href="running" class="active"' in response.text


def test_running_page_shows_no_activities_message_when_none_synced(tmp_path):
    response = _client(tmp_path).get("/running")

    assert response.status_code == 200
    assert "No activities synced yet." in response.text


def test_running_page_groups_by_monday_sunday_week(tmp_path):
    from app import db

    settings = make_settings(tmp_path)
    conn = db.connect(settings.db_path)
    # 2026-06-29 is a Monday; 2026-07-02 is the Thursday of the same week.
    # 2026-07-06 is the following Monday (next week).
    conn.execute(
        """
        INSERT INTO activities (
            activity_id, activity_name, activity_type, start_time_local, start_time_gmt,
            distance_meters, synced_at
        ) VALUES
            (1, 'Mon Run', 'running', '2026-06-29 06:00:00', '2026-06-29 13:00:00', 5000.0,
             datetime('now')),
            (2, 'Thu Run', 'running', '2026-07-02 06:00:00', '2026-07-02 13:00:00', 3000.0,
             datetime('now')),
            (3, 'Next Mon Run', 'running', '2026-07-06 06:00:00', '2026-07-06 13:00:00', 10000.0,
             datetime('now'))
        """
    )
    conn.commit()
    conn.close()

    response = TestClient(mfa_web_server.create_app(settings)).get("/running")

    assert response.status_code == 200
    # Week of 2026-06-29 sums the Monday + Thursday runs (5km + 3km = 8.00 km).
    assert "2026-06-29" in response.text
    assert "8.00 km" in response.text
    # The following week has only the 10km run, and appears first (most recent week first).
    assert "2026-07-06" in response.text
    assert "10.00 km" in response.text
    assert response.text.index("2026-07-06") < response.text.index("2026-06-29")


def test_start_reports_clear_error_when_credentials_missing(tmp_path):
    # Real production incident: the mfa-web s6 service's `run` script never exported
    # GARMIN_USERNAME/GARMIN_PASSWORD (unlike sync-scheduler's), so Settings always saw empty
    # credentials and the first login attempt (no cached session yet, the whole point of this
    # UI) hit garminconnect's generic "Username and password are required" — this checks the
    # app-level guard added alongside the run-script fix, so a misconfigured install still fails
    # clearly instead of relying on the library's message.
    settings = make_settings(tmp_path)
    blank_settings = Settings(**{**settings.__dict__, "garmin_username": "", "garmin_password": ""})
    app = mfa_web_server.create_app(blank_settings)
    client = TestClient(app)

    response = client.post("/start")

    assert response.status_code == 200
    assert "garmin_username and garmin_password are not set" in response.text


def test_start_success_without_mfa(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = (None, None)
        mock_cls.return_value = mock_garmin

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert (
        "No valid Garmin Connect session" in response.text
        or "Already logged in" in response.text
    )


def test_start_wraps_auth_error(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.side_effect = GarminConnectAuthenticationError("bad credentials")
        mock_cls.return_value = mock_garmin

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert "Login failed" in response.text
    assert "bad credentials" in response.text


def test_start_wraps_transport_error(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.side_effect = requests.exceptions.ConnectionError("no route")
        mock_cls.return_value = mock_garmin

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert "Could not reach Garmin Connect" in response.text


def test_start_never_returns_a_raw_500_on_unexpected_error(tmp_path):
    # A real production incident: an exception other than GarminConnectAuthenticationError (e.g.
    # an unexpected response shape from Garmin) and this route had no catch-all, so it crashed to
    # Starlette's generic 500 page instead of a diagnosable message.
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.side_effect = ValueError("unexpected Garmin response shape")
        mock_cls.return_value = mock_garmin

        response = _client(tmp_path).post("/start")

    assert response.status_code == 200
    assert "Login failed unexpectedly" in response.text


def test_start_needs_mfa_then_verify_succeeds(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = ("needs_mfa", None)
        mock_cls.return_value = mock_garmin

        client = _client(tmp_path)
        start_response = client.post("/start")
        assert "multi-factor authentication code" in start_response.text

        verify_response = client.post("/verify", data={"code": "123456"})

    assert verify_response.status_code == 200
    assert "Logged in successfully" in verify_response.text
    mock_garmin.resume_login.assert_called_once_with({}, "123456")
    assert mfa_web_server._pending_garmin is None
    # Regression check: a real production incident where a "successful" MFA login was never
    # actually saved, because Garmin.login()/resume_login() skip persisting to disk on the
    # return_on_mfa=True path this module has to use (see mfa_login.py's module docstring) — the
    # web UI kept showing "not logged in" even after login had genuinely succeeded.
    mock_garmin.client.dump.assert_called_once_with(str(tmp_path / "garmin_tokens"))


def test_verify_wraps_auth_error(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = ("needs_mfa", None)
        mock_garmin.resume_login.side_effect = GarminConnectAuthenticationError(
            "MFA verification failed"
        )
        mock_cls.return_value = mock_garmin

        client = _client(tmp_path)
        client.post("/start")
        verify_response = client.post("/verify", data={"code": "000000"})

    assert verify_response.status_code == 200
    assert "MFA verification failed" in verify_response.text


def test_verify_wraps_transport_error(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = ("needs_mfa", None)
        mock_garmin.resume_login.side_effect = requests.exceptions.Timeout("timed out")
        mock_cls.return_value = mock_garmin

        client = _client(tmp_path)
        client.post("/start")
        verify_response = client.post("/verify", data={"code": "000000"})

    assert verify_response.status_code == 200
    assert "Could not reach Garmin Connect" in verify_response.text


def test_verify_never_returns_a_raw_500_on_unexpected_error(tmp_path):
    with patch("app.mfa_web.server.Garmin") as mock_cls:
        mock_garmin = MagicMock()
        mock_garmin.login.return_value = ("needs_mfa", None)
        mock_garmin.resume_login.side_effect = ValueError("unexpected Garmin response shape")
        mock_cls.return_value = mock_garmin

        client = _client(tmp_path)
        client.post("/start")
        verify_response = client.post("/verify", data={"code": "000000"})

    assert verify_response.status_code == 200
    assert "Verification failed unexpectedly" in verify_response.text


def test_verify_without_pending_flow_shows_error(tmp_path):
    response = _client(tmp_path).post("/verify", data={"code": "123456"})

    assert response.status_code == 200
    assert "No login is currently waiting" in response.text


def test_sync_route_reports_activity_count(tmp_path):
    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_sync_once", return_value=5
    ) as mock_run:
        response = _client(tmp_path).post("/sync")

    assert response.status_code == 200
    assert "Synced 5 activities" in response.text
    mock_run.assert_called_once()


def test_sync_route_uses_singular_wording_for_one_activity(tmp_path):
    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_sync_once", return_value=1
    ):
        response = _client(tmp_path).post("/sync")

    assert response.status_code == 200
    assert "Synced 1 activity." in response.text


def test_sync_route_wraps_auth_error(tmp_path):
    from app.sync.garmin_client import GarminAuthError

    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_sync_once",
        side_effect=GarminAuthError("requires a multi-factor authentication (MFA) code"),
    ):
        response = _client(tmp_path).post("/sync")

    assert response.status_code == 200
    assert "Sync failed" in response.text
    assert "multi-factor authentication" in response.text


def test_sync_route_wraps_api_error(tmp_path):
    from app.sync.garmin_client import GarminAPIError

    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_sync_once", side_effect=GarminAPIError("Failed to fetch activities")
    ):
        response = _client(tmp_path).post("/sync")

    assert response.status_code == 200
    assert "Sync failed" in response.text
    assert "Failed to fetch activities" in response.text


def test_sync_route_never_returns_a_raw_500_on_unexpected_error(tmp_path):
    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_sync_once", side_effect=ValueError("unexpected shape")
    ):
        response = _client(tmp_path).post("/sync")

    assert response.status_code == 200
    assert "Sync failed unexpectedly" in response.text


def test_settings_tab_shows_nav_with_settings_active(tmp_path):
    response = _client(tmp_path).get("/settings")

    assert response.status_code == 200
    assert '<nav class="tabs">' in response.text
    assert 'href="settings" class="active"' in response.text


def test_settings_tab_shows_backfill_form(tmp_path):
    response = _client(tmp_path).get("/settings")

    assert response.status_code == 200
    assert 'action="backfill"' in response.text
    assert 'input type="date" name="start_date"' in response.text


def test_backfill_route_reports_activity_count(tmp_path):
    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_backfill_sync", return_value=42
    ) as mock_run:
        response = _client(tmp_path).post("/backfill", data={"start_date": "2020-01-01"})

    assert response.status_code == 200
    assert "Backfilled 42 activities since 2020-01-01" in response.text
    mock_run.assert_called_once()
    assert mock_run.call_args.args[2] == "2020-01-01"


def test_backfill_route_uses_singular_wording_for_one_activity(tmp_path):
    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_backfill_sync", return_value=1
    ):
        response = _client(tmp_path).post("/backfill", data={"start_date": "2020-01-01"})

    assert response.status_code == 200
    assert "Backfilled 1 activity since 2020-01-01" in response.text


def test_backfill_route_requires_a_start_date(tmp_path):
    response = _client(tmp_path).post("/backfill", data={"start_date": ""})

    assert response.status_code == 200
    assert "Choose a start date" in response.text


def test_backfill_route_wraps_bad_date_value_error(tmp_path):
    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_backfill_sync",
        side_effect=ValueError("startdate must be in format 'YYYY-MM-DD', got: garbage"),
    ):
        response = _client(tmp_path).post("/backfill", data={"start_date": "garbage"})

    assert response.status_code == 200
    assert "Invalid start date" in response.text
    assert "YYYY-MM-DD" in response.text


def test_backfill_route_wraps_auth_error(tmp_path):
    from app.sync.garmin_client import GarminAuthError

    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_backfill_sync",
        side_effect=GarminAuthError("requires a multi-factor authentication (MFA) code"),
    ):
        response = _client(tmp_path).post("/backfill", data={"start_date": "2020-01-01"})

    assert response.status_code == 200
    assert "Backfill failed" in response.text
    assert "multi-factor authentication" in response.text


def test_backfill_route_wraps_api_error(tmp_path):
    from app.sync.garmin_client import GarminAPIError

    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_backfill_sync",
        side_effect=GarminAPIError("Failed to fetch activities since 2020-01-01"),
    ):
        response = _client(tmp_path).post("/backfill", data={"start_date": "2020-01-01"})

    assert response.status_code == 200
    assert "Backfill failed" in response.text
    assert "Failed to fetch activities" in response.text


def test_backfill_route_never_returns_a_raw_500_on_unexpected_error(tmp_path):
    with patch("app.mfa_web.server.GarminClient"), patch(
        "app.mfa_web.server.run_backfill_sync", side_effect=RuntimeError("unexpected shape")
    ):
        response = _client(tmp_path).post("/backfill", data={"start_date": "2020-01-01"})

    assert response.status_code == 200
    assert "Backfill failed unexpectedly" in response.text


def test_format_timestamp_drops_microseconds_and_offset():
    assert (
        mfa_web_server._format_timestamp("2026-07-05T07:06:51.539869+00:00")
        == "2026-07-05 07:06 UTC"
    )


def test_format_timestamp_handles_missing_value():
    assert mfa_web_server._format_timestamp(None) == "unknown"


def test_format_timestamp_falls_back_to_raw_string_on_bad_input():
    assert mfa_web_server._format_timestamp("not-a-timestamp") == "not-a-timestamp"


def test_format_activity_time_has_no_utc_label():
    # Garmin's startTimeLocal is the activity's *local* time, not UTC -- unlike
    # _format_timestamp, this must never claim it's UTC.
    assert mfa_web_server._format_activity_time("2026-07-01 06:30:00") == "2026-07-01 06:30"


def test_format_activity_time_handles_missing_value():
    assert mfa_web_server._format_activity_time(None) == "unknown"


def test_format_activity_time_falls_back_to_raw_string_on_bad_input():
    assert mfa_web_server._format_activity_time("not-a-timestamp") == "not-a-timestamp"


def test_format_distance_converts_meters_to_km():
    assert mfa_web_server._format_distance(5000.0) == "5.00 km"


def test_format_distance_handles_missing_value():
    assert mfa_web_server._format_distance(None) == "—"
    assert mfa_web_server._format_distance(0) == "—"


def test_weekly_distance_returns_empty_when_db_missing(tmp_path):
    assert mfa_web_server._weekly_distance(str(tmp_path / "no_such.db")) == []


def test_weekly_distance_skips_malformed_and_missing_data(tmp_path):
    from app import db

    db_path = str(tmp_path / "stridesync.db")
    conn = db.connect(db_path)
    conn.execute(
        """
        INSERT INTO activities (
            activity_id, activity_name, activity_type, start_time_local, start_time_gmt,
            distance_meters, synced_at
        ) VALUES
            (1, 'Bad timestamp', 'running', 'not-a-timestamp', 'x', 5000.0, datetime('now')),
            (2, 'No distance', 'running', '2026-06-29 06:00:00', 'x', NULL, datetime('now'))
        """
    )
    conn.commit()
    conn.close()

    weeks = mfa_web_server._weekly_distance(db_path)

    # The malformed-timestamp row is skipped entirely; the missing-distance row still counts as
    # a week with 0.0 km rather than crashing.
    assert len(weeks) == 1
    assert weeks[0]["distance_km"] == 0.0
