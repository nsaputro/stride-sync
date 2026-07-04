"""Adds a human-like delay before submitting the Garmin SSO login form.

Live testing showed that TLS-fingerprint impersonation alone (`garmy_tls_impersonation.py`) did
not get past Garmin's Cloudflare bot challenge on the SSO signin page — the same 401 with
`server=cloudflare`/`cf-ray` persisted even with `curl_cffi` impersonating Chrome's TLS
fingerprint. `python-garminconnect` (which does get past this) does the same TLS impersonation
*and* inserts a randomized delay between fetching the login page and submitting credentials —
its widget-flow login (the same `/sso/embed` + `/sso/signin` flow `garmy` uses) waits 3-8 seconds,
treating request *timing* as a separate Cloudflare bot-detection signal from the TLS handshake:
a script that GETs a login page and POSTs credentials within milliseconds looks robotic
regardless of how convincing its TLS fingerprint is.

`garmy.auth.sso.login()` fetches the CSRF token via a GET, then immediately calls
`_perform_initial_login()` to POST credentials, with no delay between them. Patching
`_perform_initial_login` to sleep first (rather than reimplementing `login()`'s multi-step flow
here) reproduces the same GET-then-wait-then-POST timing without duplicating any of garmy's own
logic.

Call `apply()` once per process, before constructing the first `AuthClient` — alongside
`garmy_ua_override.apply()`/`garmy_tls_impersonation.apply()`, which every entry point that talks
to Garmin already calls.
"""

from __future__ import annotations

import os
import random
import time

DEFAULT_MIN_DELAY_SECONDS = 3.0
DEFAULT_MAX_DELAY_SECONDS = 8.0

_applied = False


def apply() -> None:
    """Idempotently patch garmy's SSO login to pause before submitting credentials."""
    global _applied
    if _applied:
        return

    import garmy.auth.sso as _sso

    min_delay = float(os.environ.get("GARMIN_LOGIN_DELAY_MIN_S", DEFAULT_MIN_DELAY_SECONDS))
    max_delay = float(os.environ.get("GARMIN_LOGIN_DELAY_MAX_S", DEFAULT_MAX_DELAY_SECONDS))

    original_perform_initial_login = _sso._perform_initial_login

    def _delayed_perform_initial_login(auth_client, email, password, csrf_token, signin_params):
        time.sleep(random.uniform(min_delay, max_delay))
        return original_perform_initial_login(
            auth_client, email, password, csrf_token, signin_params
        )

    _sso._perform_initial_login = _delayed_perform_initial_login

    _applied = True
