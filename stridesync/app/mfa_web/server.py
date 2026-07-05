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
from html import escape
from typing import Any, Dict, Optional

from garminconnect import Garmin, GarminConnectAuthenticationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
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
from app.sync.scheduler import run_sync_once

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_pending_garmin: Optional[Garmin] = None

_STYLE = """
  body { font-family: sans-serif; max-width: 32rem; margin: 3rem auto; padding: 0 1rem; }
  input, button { font-size: 1rem; padding: 0.4rem; }
  .error { color: #b00020; }
  .ok { color: #0a7d28; }
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html>"
        f'<html><head><meta charset="utf-8"><title>StrideSync — {escape(title)}</title>'
        f"<style>{_STYLE}</style></head>"
        f"<body><h1>StrideSync</h1>{body}</body></html>"
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

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
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
    html = f"<p>Total activities synced: {summary['total_activities']}</p>"

    last_sync = summary["last_sync"]
    if last_sync is None:
        return html + "<p>No sync has run yet.</p>"

    css_class = "ok" if last_sync["status"] == "success" else "error"
    when = last_sync["finished_at"] or last_sync["started_at"]
    html += (
        f'<p class="{css_class}">Last sync: {escape(last_sync["status"])} at {escape(when)} '
        f'({_activity_count(last_sync["activities_synced"])})</p>'
    )
    if last_sync["status"] != "success" and last_sync["error_message"]:
        html += f'<p class="error">Last sync error: {escape(last_sync["error_message"])}</p>'
    return html


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

    body = f"{message}{_sync_summary_html(settings)}"
    body += (
        f'<form method="post" action="start"><button type="submit">{escape(button_label)}'
        "</button></form>"
    )
    if has_session:
        body += (
            '<form method="post" action="sync"><button type="submit">Sync now</button></form>'
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
            '<input type="text" name="code" placeholder="MFA code" autofocus required>'
            '<button type="submit">Verify</button></form>',
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
            Route("/start", start, methods=["POST"]),
            Route("/verify", verify, methods=["POST"]),
            Route("/sync", sync, methods=["POST"]),
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
