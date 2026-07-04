"""Impersonates a real browser's TLS fingerprint for Garmin SSO login requests.

Garmin put Cloudflare in front of their SSO login in March 2026 (see PROJECT_PLAN.md's "known
risk" section). Confirmed via live testing: even after correcting garmy's malformed User-Agent
(see `garmy_ua_override.py`), a login attempt got a Cloudflare bot-challenge page back
(`server: cloudflare`, a `cf-ray` header, an HTML body with `class="no-js"`), while the identical
request succeeded instantly from a real browser on the same account/network. Cloudflare's bot
management here evidently checks the TLS/JA3 handshake fingerprint itself — that happens before
any HTTP request is even sent, so no amount of header tweaking can fix it.

`curl_cffi` (a `requests`-API-compatible HTTP client backed by libcurl, capable of impersonating
a real browser's TLS fingerprint) is the fix `python-garminconnect` adopted for this exact
problem. Applied narrowly here: only `garmy`'s `AuthHttpClient` (used exclusively for the SSO
login flow) is patched to use it — `APIClient`'s ordinary data-fetch requests (against
`connectapi.garmin.com`, not gated behind this same Cloudflare rule as far as observed) are
untouched, so this doesn't risk regressing anything that already works.

Two compatibility gaps `garmy` doesn't know about, both handled here:
- `curl_cffi.requests.Session` has no `.adapters`/`.mount()` (it isn't built on `requests`/
  urllib3 at all) — `garmy.auth.sso.GarminOAuth1Session.__init__` unconditionally reads
  `parent.adapters["https://"]` to inherit adapter/proxy/verify settings from the auth session
  when exchanging the login ticket for OAuth1/OAuth2 tokens. Patched to skip that inheritance
  when the parent doesn't have it — proxies aren't used in this deployment, so nothing is
  actually lost by not inheriting them.
- `curl_cffi.requests.exceptions.RequestException` is not a subclass of
  `requests.exceptions.RequestException` — see `garmin_client.py`'s `TRANSPORT_ERRORS`, which
  includes both so every entry point's error handling still catches failures regardless of which
  transport raised them.

No automatic per-request retry (unlike the plain-`requests` session `garmy` normally builds,
which mounts an `HTTPAdapter` with a `Retry` strategy) — curl_cffi doesn't have an equivalent
built-in, and a login attempt isn't retried automatically by any of our own code either (the
caller — scheduled sync, the CLI, or the web UI — is what decides whether to try again).

Call `apply()` once per process, before constructing the first `AuthClient` — every entry point
that talks to Garmin already calls `garmy_ua_override.apply()` alongside this at import time.
"""

from __future__ import annotations

import os

DEFAULT_IMPERSONATE = "chrome"

_applied = False


def apply() -> None:
    """Idempotently patch garmy's auth HTTP client to use TLS-impersonating requests."""
    global _applied
    if _applied:
        return

    import garmy.auth.client as _auth_client_module
    import garmy.auth.sso as _sso

    impersonate = os.environ.get("GARMIN_TLS_IMPERSONATE", DEFAULT_IMPERSONATE)

    def _create_impersonating_session(self, retries, user_agent):
        from curl_cffi import requests as curl_requests

        session = curl_requests.Session(impersonate=impersonate)
        session.headers.update(self._get_default_headers(user_agent))
        return session

    _auth_client_module.AuthHttpClient._create_session = _create_impersonating_session

    _original_oauth1_init = _sso.GarminOAuth1Session.__init__

    def _patched_oauth1_init(self, parent=None, **kwargs):
        if parent is not None and not hasattr(parent, "adapters"):
            # A curl_cffi session has nothing to inherit adapters/proxies/verify from — build
            # the OAuth1Session as if no parent were given, rather than crashing on
            # parent.adapters["https://"].
            _original_oauth1_init(self, parent=None, **kwargs)
            return
        _original_oauth1_init(self, parent=parent, **kwargs)

    _sso.GarminOAuth1Session.__init__ = _patched_oauth1_init

    _applied = True
