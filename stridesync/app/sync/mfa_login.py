"""Shared Garmin MFA login flow, used by both the CLI bootstrap and the ingress web UI.

`app/sync/bootstrap_login.py` (terminal/`docker exec`) and `app/mfa_web/server.py` (HA ingress,
for users without terminal access) both need the same two-step flow: attempt login (preferring a
cached/refreshed session over a fresh one — see `Garmin.login()`'s own tokenstore-first logic),
and handle the `("needs_mfa", None)` result `python-garminconnect` returns when
`return_on_mfa=True` and an MFA code is needed. Factored out here so that flow logic exists in
exactly one place instead of being copy-pasted between a CLI and a web handler.

Unlike `garmy` (this module's previous dependency — see `garmin_client.py`'s module docstring
for why it was replaced), `python-garminconnect` keeps pending MFA state on the `Garmin`/`Client`
instance itself rather than an external state object, so there is no `mfa_state` to thread
through to `resume_login()` — the caller just needs to keep the same `Garmin` instance alive
between `start_login()` and `resume_login()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from garminconnect import Garmin


@dataclass(frozen=True)
class LoginResult:
    """A login attempt that did not require an MFA code."""


@dataclass(frozen=True)
class NeedsMfa:
    """A login attempt that needs an MFA code to complete — see `resume_login`."""


def start_login(garmin: Garmin, token_dir: Optional[str]) -> Union[LoginResult, NeedsMfa]:
    """Log in, preferring a cached/refreshed session over a fresh one.

    Raises:
        garminconnect.GarminConnectAuthenticationError: on bad credentials or a broken login
            chain. With `return_on_mfa=True` (required on the `Garmin` instance passed in), an
            MFA requirement is signaled via the return value instead of an exception.
    """
    mfa_status, _legacy_token = garmin.login(tokenstore=token_dir)
    if mfa_status == "needs_mfa":
        return NeedsMfa()
    return LoginResult()


def resume_login(garmin: Garmin, mfa_code: str) -> None:
    """Complete a pending MFA login on the same `Garmin` instance `start_login` was called on.

    Raises:
        garminconnect.GarminConnectAuthenticationError: if the code is wrong, expired, or
            verification fails.
    """
    garmin.resume_login({}, mfa_code)
