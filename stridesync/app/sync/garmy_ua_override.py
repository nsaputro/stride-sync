"""Overrides garmy's Android User-Agent for Garmin SSO requests.

garmy's Android user agent (`garmy.core.config.UserAgents.ANDROID_APP`) is the literal Android
package name `"com.garmin.android.apps.connectmobile"` — not a real User-Agent string, unlike
garmy's own correctly-formatted iOS constant (`"GCM-iOS-5.12.24"`). It's also identical across
every garmy install, an easy fingerprint for Garmin/Cloudflare's bot detection to single out.
This surfaced as a real production 401 on the plain SSO signin page (before credentials were
even submitted) that disappeared when the exact same URL was opened in a real browser on the
same account/network — see PROJECT_PLAN.md's "known risk" section.

Two separate places need the override, since garmy sources this UA two different ways:
- `AuthHttpClient`'s session default header (used for `/sso/embed` and `/sso/signin` — the
  request that's actually failing) reads `garmy.core.config.get_user_agent()` fresh every time
  an `AuthClient()` is constructed, so garmy's own public `set_config()` API works for this.
- `garmy.auth.sso`'s OAuth1/OAuth2 token-exchange calls read a `USER_AGENT` constant computed
  once at *module import time* — `set_config()` has no effect on it after the fact (importing
  anything from `garmy` at all already runs `garmy/__init__.py`, which imports `garmy.auth.sso`
  as a side effect, before any of our own code can run), so it must be patched directly on the
  already-imported module instead.

Call `apply()` once per process, before constructing the first `AuthClient` — every entry point
that talks to Garmin (`garmin_client.py`, `bootstrap_login.py`, `mfa_web/server.py`) does so
right after its own `from garmy import ...`.

This is a workaround for garmy's internals, not its public API. Expected to become unnecessary
(and should be removed) if/when garmy fixes `UserAgents.ANDROID_APP` upstream.
"""

from __future__ import annotations

import dataclasses
import os

DEFAULT_ANDROID_USER_AGENT = "GCM-Android-5.7.2.0"

_applied = False


def apply() -> None:
    """Idempotently override garmy's Android SSO User-Agent for this process."""
    global _applied
    if _applied:
        return

    import garmy.auth.sso as _sso
    from garmy.core.config import get_config, set_config

    user_agent = os.environ.get("GARMIN_ANDROID_USER_AGENT", DEFAULT_ANDROID_USER_AGENT)

    set_config(dataclasses.replace(get_config(), android_user_agent=user_agent))
    _sso.USER_AGENT = {"User-Agent": user_agent}

    _applied = True
