"""Ingress web UI for the one-time Garmin MFA login — python3 -m app.mfa_web.server

`python3 -m app.sync.bootstrap_login` (see that module) already performs this same one-time
login over a terminal. This is the same flow — reusing `app/sync/mfa_login.py`'s shared
start/resume logic — for HA users without terminal/`docker exec` access, which not every HA user
has set up. Flagged by the same user who hit the original MFA gap.

Reached through Home Assistant ingress (`ingress: true` + `ingress_port` in config.yaml). HA
proxies ingress traffic under a per-install path prefix it controls (e.g.
`/api/hassio_ingress/<token>/`) — every link/form action in this module is therefore a *relative*
path (never a leading "/"), so the browser resolves it against that prefix automatically instead
of this code needing to know or construct it.

There is exactly one Garmin account per add-on install, so in-flight MFA login state is a single
module-level slot guarded by a lock — not a per-visitor session store.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from html import escape
from typing import Any, Dict, List, Optional

from garminconnect import Garmin, GarminConnectAuthenticationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from app.config import Settings
from app.sync import mfa_login
from app.sync.garmin_client import (
    TRANSPORT_ERRORS,
    GarminAPIError,
    GarminAuthError,
    GarminClient,
    describe_transport_error,
)
from app.sync.scheduler import run_backfill_sync, run_sync_once

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_pending_garmin: Optional[Garmin] = None

_STYLE = """
  :root {
    color-scheme: light dark;
    --bg: #f2f3f5; --card: #ffffff; --text: #1a1a1a; --muted: #6b7280; --border: #e3e5e8;
    --ok: #0a7d28; --ok-bg: #e6f4ea; --error: #b00020; --error-bg: #fbe9eb;
    --primary: #1f6feb; --primary-text: #ffffff;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #16181c; --card: #202329; --text: #e7e9ea; --muted: #9aa0a6; --border: #33373d;
      --ok: #4ade80; --ok-bg: #113420; --error: #f87171; --error-bg: #3a1a1d;
      --primary: #4c8dff; --primary-text: #0b1220;
    }
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text);
    max-width: 26rem; margin: 0 auto; padding: 1.5rem 1rem 3rem;
  }
  h1 { font-size: 1.4rem; margin: 0.25rem 0 1rem; }
  nav.tabs { display: flex; gap: 0.5rem; margin-bottom: 1rem; border-bottom: 1px solid var(--border); }
  nav.tabs a {
    display: inline-block; padding: 0.5rem 0.1rem; margin-bottom: -1px; text-decoration: none;
    color: var(--muted); font-weight: 600; border-bottom: 2px solid transparent;
  }
  nav.tabs a.active { color: var(--text); border-bottom-color: var(--primary); }
  ul.week-list { list-style: none; margin: 0; padding: 0; }
  ul.week-list li {
    display: flex; justify-content: space-between; gap: 0.75rem; padding: 0.5rem 0;
    border-top: 1px solid var(--border);
  }
  ul.week-list li:first-child { border-top: none; }
  .week-range { color: var(--muted); }
  .week-total { font-weight: 600; }
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 0.75rem;
    padding: 1.1rem 1.25rem; margin-bottom: 1rem;
  }
  p { line-height: 1.5; margin: 0.5rem 0; }
  p.stat { font-weight: 600; }
  h2 { font-size: 0.95rem; font-weight: 600; margin: 1rem 0 0.4rem; color: var(--muted); }
  ul.activity-list { list-style: none; margin: 0; padding: 0; }
  ul.activity-list li {
    display: flex; justify-content: space-between; gap: 0.75rem; padding: 0.5rem 0;
    border-top: 1px solid var(--border);
  }
  ul.activity-list li:first-child { border-top: none; }
  .activity-name { font-weight: 600; }
  .activity-meta { color: var(--muted); text-align: right; white-space: nowrap; }
  p.error {
    color: var(--error); background: var(--error-bg); padding: 0.6rem 0.75rem;
    border-radius: 0.5rem;
  }
  p.ok { color: var(--ok); font-weight: 600; }
  form { margin: 0.6rem 0; }
  button, input[type=text], input[type=date] {
    font-size: 1rem; padding: 0.7rem 1rem; border-radius: 0.5rem; border: 1px solid var(--border);
    width: 100%; font-family: inherit;
  }
  button {
    cursor: pointer; font-weight: 600; background: var(--card); color: var(--text);
  }
  button.primary { background: var(--primary); color: var(--primary-text); border-color: var(--primary); }
  button:disabled { opacity: 0.6; cursor: default; }
  input[type=text], input[type=date] {
    background: var(--card); color: var(--text); margin-bottom: 0.5rem;
  }
  progress { width: 100%; height: 0.9rem; margin: 0.5rem 0; accent-color: var(--primary); }
  a { color: var(--primary); }
"""

_SCRIPT = """
<script>
document.addEventListener("submit", function (event) {
  var button = event.target.querySelector("button[type=submit]");
  if (button) {
    button.disabled = true;
    button.textContent = "Working…";
  }
});
</script>
"""


_TABS = (
    ("dashboard", ".", "Dashboard"),
    ("running", "running", "Running"),
    ("settings", "settings", "Settings"),
)


def _nav_html(active_tab: str) -> str:
    active_class = ' class="active"'
    links = "".join(
        f'<a href="{href}"{active_class if tab_id == active_tab else ""}>{escape(label)}</a>'
        for tab_id, href, label in _TABS
    )
    return f'<nav class="tabs">{links}</nav>'


def _page(title: str, body: str, active_tab: str = "dashboard") -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html>"
        "<html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>StrideSync — {escape(title)}</title>"
        f"<style>{_STYLE}</style>"
        "</head>"
        f"<body><h1>StrideSync</h1>{_nav_html(active_tab)}"
        f'<div class="card">{body}</div>{_SCRIPT}</body></html>'
    )


def _has_cached_session(token_dir: Optional[str]) -> bool:
    """Best-effort check for a previously saved session, without attempting a login.

    `python-garminconnect` only knows whether a session is valid once `Garmin.login()` has
    loaded it — there's no equivalent to check beforehand without also attempting a network
    call, which a passive status page shouldn't do. Checking whether the token file exists at
    all is a reasonable proxy for display purposes (matches `Client.dump()`'s own naming: a
    directory tokenstore always resolves to `<token_dir>/garmin_tokens.json`).
    """
    if not token_dir:
        return False
    return os.path.exists(os.path.join(token_dir, "garmin_tokens.json"))


def _activity_count(count: int) -> str:
    return f"{count} activit{'y' if count == 1 else 'ies'}"


def _format_timestamp(iso_str: Optional[str]) -> str:
    """Format a sync_log/training_baseline timestamp for display — those are always written by
    `datetime.now(timezone.utc).isoformat()` (see scheduler.py), so they're always UTC; this just
    drops the microseconds/offset noise raw isoformat() output has (e.g.
    "2026-07-05T07:06:51.539869+00:00") that isn't useful to a person glancing at the panel.
    """
    if not iso_str:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return iso_str
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _format_activity_time(raw: Optional[str]) -> str:
    """Format an activity's `start_time_local` for display.

    Unlike `_format_timestamp`, this is deliberately NOT labeled "UTC" — Garmin's `startTimeLocal`
    is the activity's local time at wherever it was recorded (not the server's timezone, and not
    UTC), so a timezone label here would just be wrong.
    """
    if not raw:
        return "unknown"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    return dt.strftime("%Y-%m-%d %H:%M")


def _connect_readonly(db_path: str) -> sqlite3.Connection:
    """Open a read-only connection with a busy timeout.

    Without a timeout, a read hitting the DB while the sync scheduler or a backfill holds a
    write transaction raises "database is locked" immediately instead of waiting the write out.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _sync_summary(db_path: str) -> Dict[str, Any]:
    """Best-effort total-activities-synced + last-sync-outcome summary for display.

    Opens its own read-only connection rather than reuse `app/mcp/server.py`'s (which serves the
    same `sync_log`/`activities` data to MCP clients) — this module and the MCP server are meant
    to stay independently runnable (CLAUDE.md), so importing one from the other for a two-query
    lookup isn't worth coupling them. Returns defaults, not an error, if the DB file doesn't
    exist yet (e.g. the sync-scheduler service hasn't completed its first pass).
    """
    if not os.path.exists(db_path):
        return {"total_activities": 0, "last_sync": None}

    conn = _connect_readonly(db_path)
    try:
        total_activities = conn.execute("SELECT COUNT(*) AS n FROM activities").fetchone()["n"]
        last_sync_row = conn.execute(
            """
            SELECT started_at, finished_at, status, activities_synced, error_message
            FROM sync_log ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()

    return {
        "total_activities": total_activities,
        "last_sync": dict(last_sync_row) if last_sync_row is not None else None,
    }


def _sync_summary_html(settings: Settings) -> str:
    summary = _sync_summary(settings.db_path)
    html = f'<p class="stat">Total activities synced: {summary["total_activities"]}</p>'

    last_sync = summary["last_sync"]
    if last_sync is None:
        return html + "<p>No sync has run yet.</p>"

    css_class = "ok" if last_sync["status"] == "success" else "error"
    when = _format_timestamp(last_sync["finished_at"] or last_sync["started_at"])
    html += (
        f'<p class="{css_class}">Last sync: {escape(last_sync["status"])} at {escape(when)} '
        f'({_activity_count(last_sync["activities_synced"])})</p>'
    )
    if last_sync["status"] != "success" and last_sync["error_message"]:
        html += f'<p class="error">Last sync error: {escape(last_sync["error_message"])}</p>'
    return html


def _format_distance(distance_meters: Optional[float]) -> str:
    if not distance_meters:
        return "—"
    return f"{distance_meters / 1000:.2f} km"


def _recent_activities(db_path: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Best-effort last-`limit` synced activities for display — same "no DB yet" tolerance as
    `_sync_summary` (see its docstring for why this doesn't share a connection helper with
    `app/mcp/server.py`).
    """
    if not os.path.exists(db_path):
        return []

    conn = _connect_readonly(db_path)
    try:
        rows = conn.execute(
            """
            SELECT activity_id, activity_name, activity_type, start_time_local, distance_meters
            FROM activities
            ORDER BY start_time_local DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _recent_activities_html(settings: Settings) -> str:
    activities = _recent_activities(settings.db_path)
    if not activities:
        return ""

    items = "".join(
        '<li><span class="activity-name">'
        f'{escape(activity["activity_name"] or activity["activity_type"] or "Activity")}'
        "</span>"
        f'<span class="activity-meta">{escape(_format_activity_time(activity["start_time_local"]))}'
        f" · {escape(_format_distance(activity['distance_meters']))}</span></li>"
        for activity in activities
    )
    return f'<h2>Recent activities</h2><ul class="activity-list">{items}</ul>'


def _weekly_distance(db_path: str, weeks: int = 12) -> List[Dict[str, Any]]:
    """Total distance per calendar week (Monday-Sunday), most recent week first.

    Grouped in Python rather than via SQLite date modifiers — `start_time_local` is Garmin's
    local-time string for the activity (see `_format_activity_time`), and Python's
    `date.weekday()` (Monday=0) makes "which Monday does this date belong to" a one-line, easily
    verified computation rather than a `strftime`/`'weekday N'` modifier expression that's easy
    to get subtly wrong. Same "no DB yet" tolerance as `_sync_summary`/`_recent_activities`.
    """
    if not os.path.exists(db_path):
        return []

    conn = _connect_readonly(db_path)
    try:
        rows = conn.execute(
            "SELECT start_time_local, distance_meters FROM activities"
        ).fetchall()
    finally:
        conn.close()

    totals: Dict[Any, float] = {}
    for row in rows:
        raw = row["start_time_local"]
        if not raw:
            continue
        try:
            activity_date = datetime.fromisoformat(raw).date()
        except ValueError:
            continue
        week_start = activity_date - timedelta(days=activity_date.weekday())
        totals[week_start] = totals.get(week_start, 0.0) + (row["distance_meters"] or 0.0)

    weeks_sorted = sorted(totals.items(), key=lambda kv: kv[0], reverse=True)[:weeks]
    return [
        {"week_start": week_start, "distance_km": total_meters / 1000.0}
        for week_start, total_meters in weeks_sorted
    ]


def _weekly_distance_html(settings: Settings) -> str:
    weeks = _weekly_distance(settings.db_path)
    if not weeks:
        return "<p>No activities synced yet.</p>"

    items = "".join(
        f'<li><span class="week-range">{escape(week["week_start"].strftime("%Y-%m-%d"))}</span>'
        f'<span class="week-total">{week["distance_km"]:.2f} km</span></li>'
        for week in weeks
    )
    return f'<h2>Weekly total distance</h2><ul class="week-list">{items}</ul>'


async def running(request: Request) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    return _page("Running", _weekly_distance_html(settings), active_tab="running")


def _settings_body() -> str:
    """Reflects the current backfill state, not just a static form — the "Settings" nav tab is
    reachable independently of the "/backfill" URL (e.g. the user switches to another tab and
    back), so it must show a running backfill's progress bar, not silently reset to the plain
    form and make it look like the backfill vanished.
    """
    with _backfill_lock:
        state = dict(_backfill_state)

    form_html = (
        "<h2>Backfill activities</h2>"
        "<p>Regular syncs only fetch your most recent activities. Use this to pull in older "
        "history from a specific date onward.</p>"
        '<p class="error">A wide date range can take a while and make many Garmin API calls '
        "(each activity needs several) — you'll see a progress bar once it starts, and can "
        "safely navigate away and back; it keeps running either way.</p>"
        '<form method="post" action="backfill">'
        '<input type="date" name="start_date" required>'
        '<button type="submit" class="primary">Backfill</button></form>'
    )

    if state["running"]:
        return _backfill_progress_body()

    if state["done"] and state["start_date"] is not None:
        start_date = escape(state["start_date"])
        if state["error"]:
            status_html = f'<p class="error">Last backfill failed: {escape(state["error"])}</p>'
        else:
            status_html = (
                f'<p class="ok">Last backfill: {_activity_count(state["result_count"] or 0)} '
                f"since {start_date}.</p>"
            )
        return status_html + form_html

    return form_html


async def settings_tab(request: Request) -> HTMLResponse:
    return _page("Settings", _settings_body(), active_tab="settings")


# Backfill state (see module docstring re: single-account, single-in-flight-operation design —
# same rationale as _pending_garmin above, just for a background thread instead of a multi-step
# form flow). Guarded by _backfill_lock since it's read/written from both the asyncio event loop
# thread (handling requests) and the background thread actually running the backfill.
_backfill_lock = threading.Lock()
_backfill_state: Dict[str, Any] = {
    "running": False,
    "start_date": None,
    "total": 0,
    "completed": 0,
    "done": False,
    "error": None,
    "result_count": None,
}


def _run_backfill_in_background(settings: Settings, start_date: str) -> None:
    """Runs `scheduler.run_backfill_sync` on a background thread (started by `backfill()` below)
    so the HTTP request that kicks it off can return immediately with a progress page, instead of
    blocking for however long a wide date range takes. Reports outcome via `_backfill_state`
    rather than a return value/exception, since nothing is left to receive either once the
    triggering request has already returned.
    """
    client = GarminClient(
        settings.garmin_username, settings.garmin_password, token_dir=settings.garmin_token_dir
    )

    def on_progress(completed: int, total: int) -> None:
        with _backfill_lock:
            _backfill_state["completed"] = completed
            _backfill_state["total"] = total

    error_message: Optional[str] = None
    result_count: Optional[int] = None
    try:
        result_count = run_backfill_sync(settings, client, start_date, progress_callback=on_progress)
    except ValueError as exc:
        error_message = f"Invalid start date: {exc}"
    except (GarminAuthError, GarminAPIError) as exc:
        error_message = f"Backfill failed: {exc}"
    except Exception:
        logger.exception("Unexpected error during backfill")
        error_message = "Backfill failed unexpectedly — check the add-on log for details."
    finally:
        with _backfill_lock:
            _backfill_state["running"] = False
            _backfill_state["done"] = True
            _backfill_state["error"] = error_message
            _backfill_state["result_count"] = result_count


_BACKFILL_POLL_SCRIPT = """
<script>
(function () {
  function poll() {
    fetch("backfill/status").then(function (r) { return r.json(); }).then(function (s) {
      if (s.done) {
        location.reload();
        return;
      }
      var bar = document.getElementById("backfill-bar");
      if (bar) { bar.max = s.total || 1; bar.value = s.completed || 0; }
      var status = document.getElementById("backfill-status");
      if (status) { status.textContent = (s.completed || 0) + " / " + (s.total || "?") + " activities"; }
      setTimeout(poll, 1000);
    });
  }
  poll();
})();
</script>
"""


def _backfill_progress_body() -> str:
    with _backfill_lock:
        state = dict(_backfill_state)

    start_date = escape(state["start_date"] or "")

    if state["done"]:
        if state["error"]:
            return f'<p class="error">{escape(state["error"])}</p><p><a href="settings">Back</a></p>'
        return (
            f'<p class="ok">Backfilled {_activity_count(state["result_count"] or 0)} since '
            f"{start_date}.</p>"
            '<p><a href=".">Back to dashboard</a></p>'
        )

    total = state["total"] or 0
    completed = state["completed"] or 0
    return (
        f"<p>Backfilling activities since {start_date}…</p>"
        f'<progress id="backfill-bar" value="{completed}" max="{max(total, 1)}" '
        'style="width:100%"></progress>'
        f'<p id="backfill-status">{completed} / {total if total else "?"} activities</p>'
        "<p>Feel free to navigate away — this keeps running, and this page will show the "
        "result next time you open it.</p>"
        f"{_BACKFILL_POLL_SCRIPT}"
    )


async def backfill(request: Request) -> HTMLResponse:
    """GET shows the current backfill's progress (or redirects to Settings if none has run yet
    this process); POST starts a new one. Reusing `scheduler.run_backfill_sync` on a background
    thread — see that function's docstring for why it's a separate entry point from the regular
    `run_sync_once`/"Sync now" flow (date-based, not count-based; can cover far more activities).
    """
    settings: Settings = request.app.state.settings

    if request.method == "GET":
        with _backfill_lock:
            has_run = _backfill_state["start_date"] is not None
        if not has_run:
            return RedirectResponse(url="settings", status_code=303)
        return _page("Backfill", _backfill_progress_body(), active_tab="settings")

    form = await request.form()
    start_date = str(form.get("start_date", "")).strip()

    if not start_date:
        return _page(
            "Backfill failed",
            '<p class="error">Choose a start date.</p><p><a href="settings">Back</a></p>',
            active_tab="settings",
        )

    with _backfill_lock:
        already_running = _backfill_state["running"]
        if not already_running:
            _backfill_state.update(
                {
                    "running": True,
                    "start_date": start_date,
                    "total": 0,
                    "completed": 0,
                    "done": False,
                    "error": None,
                    "result_count": None,
                }
            )

    # _backfill_progress_body() below acquires _backfill_lock itself (it's not reentrant), so it
    # must only ever be called after the `with` block above has already exited.
    if already_running:
        return _page("Backfill in progress", _backfill_progress_body(), active_tab="settings")

    threading.Thread(
        target=_run_backfill_in_background, args=(settings, start_date), daemon=True
    ).start()

    return _page("Backfill", _backfill_progress_body(), active_tab="settings")


async def backfill_status(request: Request) -> JSONResponse:
    """Polled by `_BACKFILL_POLL_SCRIPT` above roughly once a second while a backfill runs."""
    with _backfill_lock:
        return JSONResponse(
            {
                "running": _backfill_state["running"],
                "total": _backfill_state["total"],
                "completed": _backfill_state["completed"],
                "done": _backfill_state["done"],
            }
        )


def _status_body(settings: Settings) -> str:
    has_session = _has_cached_session(settings.garmin_token_dir)
    if has_session:
        message = (
            '<p class="ok">Already logged in to Garmin Connect — scheduled syncs are using '
            "this session.</p>"
        )
        button_label = "Log in again"
    else:
        message = (
            "<p>No valid Garmin Connect session yet. Click below to log in — if your account "
            "requires a multi-factor code, you'll be asked for it next.</p>"
        )
        button_label = "Log in to Garmin Connect"

    body = f"{message}{_sync_summary_html(settings)}{_recent_activities_html(settings)}"
    # The primary action is whichever one you'd reach for day-to-day: once logged in, that's
    # syncing, not logging in again — so "Sync now" gets the prominent styling and comes first.
    login_button_class = "" if has_session else " class=\"primary\""
    if has_session:
        body += (
            '<form method="post" action="sync">'
            '<button type="submit" class="primary">Sync now</button></form>'
        )
    body += (
        f'<form method="post" action="start"><button type="submit"{login_button_class}>'
        f"{escape(button_label)}</button></form>"
    )
    return body


async def index(request: Request) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    return _page("Garmin login", _status_body(settings))


async def start(request: Request) -> HTMLResponse:
    global _pending_garmin
    settings: Settings = request.app.state.settings

    if not settings.garmin_username or not settings.garmin_password:
        return _page(
            "Login failed",
            '<p class="error">Login failed: garmin_username and garmin_password are not set '
            "in the add-on configuration.</p><p><a href=\".\">Back</a></p>",
        )

    garmin = Garmin(
        email=settings.garmin_username,
        password=settings.garmin_password,
        return_on_mfa=True,
    )
    try:
        result = mfa_login.start_login(garmin, settings.garmin_token_dir)
    except GarminConnectAuthenticationError as exc:
        return _page(
            "Login failed",
            f'<p class="error">Login failed: {escape(str(exc))}</p><p><a href=".">Back</a></p>',
        )
    except TRANSPORT_ERRORS as exc:
        return _page(
            "Login failed",
            f'<p class="error">Could not reach Garmin Connect: '
            f'{escape(describe_transport_error(exc))}</p>'
            '<p><a href=".">Back</a></p>',
        )
    except Exception:
        logger.exception("Unexpected error starting Garmin login")
        return _page(
            "Login failed",
            '<p class="error">Login failed unexpectedly — check the add-on log for details.</p>'
            '<p><a href=".">Back</a></p>',
        )

    if isinstance(result, mfa_login.NeedsMfa):
        with _lock:
            _pending_garmin = garmin
        return _page(
            "Enter MFA code",
            "<p>Garmin sent a multi-factor authentication code to your registered "
            "device/email.</p>"
            '<form method="post" action="verify">'
            '<input type="text" name="code" placeholder="MFA code" autofocus required '
            'inputmode="numeric" autocomplete="one-time-code">'
            '<button type="submit" class="primary">Verify</button></form>',
        )

    return _page("Garmin login", _status_body(settings))


async def verify(request: Request) -> HTMLResponse:
    global _pending_garmin
    settings: Settings = request.app.state.settings

    form = await request.form()
    code = str(form.get("code", "")).strip()

    with _lock:
        garmin = _pending_garmin

    if garmin is None:
        return _page(
            "No login in progress",
            '<p class="error">No login is currently waiting for an MFA code — start over.</p>'
            '<p><a href=".">Back</a></p>',
        )

    try:
        mfa_login.resume_login(garmin, code, settings.garmin_token_dir)
    except GarminConnectAuthenticationError as exc:
        return _page(
            "MFA verification failed",
            f'<p class="error">MFA verification failed: {escape(str(exc))}</p>'
            '<p><a href=".">Back</a></p>',
        )
    except TRANSPORT_ERRORS as exc:
        return _page(
            "MFA verification failed",
            f'<p class="error">Could not reach Garmin Connect: '
            f'{escape(describe_transport_error(exc))}</p>'
            '<p><a href=".">Back</a></p>',
        )
    except Exception:
        logger.exception("Unexpected error verifying Garmin MFA code")
        return _page(
            "MFA verification failed",
            '<p class="error">Verification failed unexpectedly — check the add-on log for '
            "details.</p><p><a href=\".\">Back</a></p>",
        )

    with _lock:
        _pending_garmin = None

    return _page(
        "Logged in",
        '<p class="ok">Logged in successfully. Scheduled syncs will now reuse this session.</p>'
        '<p><a href=".">Back</a></p>',
    )


async def sync(request: Request) -> HTMLResponse:
    """On-demand sync, reusing the same `run_sync_once` the sync-scheduler service calls on its
    own interval — this button doesn't duplicate that logic, it just triggers it early, e.g. to
    verify a just-completed login actually works end-to-end without waiting for the next
    scheduled run.

    Blocking network calls run directly in this async handler, same as `start`/`verify` above —
    consistent with the rest of this module, and acceptable for a single-account ingress panel.
    """
    settings: Settings = request.app.state.settings
    client = GarminClient(
        settings.garmin_username, settings.garmin_password, token_dir=settings.garmin_token_dir
    )

    try:
        count = run_sync_once(settings, client)
    except (GarminAuthError, GarminAPIError) as exc:
        return _page(
            "Sync failed",
            f'<p class="error">Sync failed: {escape(str(exc))}</p><p><a href=".">Back</a></p>',
        )
    except Exception:
        logger.exception("Unexpected error during on-demand sync")
        return _page(
            "Sync failed",
            '<p class="error">Sync failed unexpectedly — check the add-on log for details.</p>'
            '<p><a href=".">Back</a></p>',
        )

    return _page(
        "Sync complete",
        f'<p class="ok">Synced {_activity_count(count)}.</p><p><a href=".">Back</a></p>',
    )


def create_app(settings: Settings) -> Starlette:
    app = Starlette(
        routes=[
            Route("/", index, methods=["GET"]),
            Route("/running", running, methods=["GET"]),
            Route("/settings", settings_tab, methods=["GET"]),
            Route("/start", start, methods=["POST"]),
            Route("/verify", verify, methods=["POST"]),
            Route("/sync", sync, methods=["POST"]),
            Route("/backfill", backfill, methods=["GET", "POST"]),
            Route("/backfill/status", backfill_status, methods=["GET"]),
        ]
    )
    app.state.settings = settings
    return app


def main() -> None:
    import uvicorn

    settings = Settings.from_env()
    logging.basicConfig(level=settings.log_level.upper())

    logger.info("Starting StrideSync MFA login web UI on port %d", settings.mfa_web_port)
    app = create_app(settings)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.mfa_web_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
