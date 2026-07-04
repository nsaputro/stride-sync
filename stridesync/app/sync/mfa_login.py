"""Shared Garmin MFA login flow, used by both the CLI bootstrap and the ingress web UI.

`app/sync/bootstrap_login.py` (terminal/`docker exec`) and `app/mfa_web/server.py` (HA ingress,
for users without terminal access) both need the same three-step flow: check for an already-
cached session, attempt a fresh login, and handle the `("needs_mfa", state)` tuple `garmy`
returns instead of raising when MFA is required (see garmin_client.py's `login()` docstring for
why a fresh login can't just be retried automatically). Factored out here so that flow logic
exists in exactly one place instead of being copy-pasted between a CLI and a web handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Union

from garmy import AuthClient


@dataclass(frozen=True)
class LoginResult:
    """A login attempt that did not require an MFA code."""

    already_authenticated: bool


@dataclass(frozen=True)
class NeedsMfa:
    """A login attempt that needs an MFA code to complete — see `resume_login`."""

    mfa_state: Dict[str, Any]


def start_login(auth_client: AuthClient, username: str, password: str) -> Union[LoginResult, NeedsMfa]:
    """Log in, preferring an already-cached session over a fresh SSO login.

    Raises:
        garmy.core.exceptions.AuthError: on bad credentials or a broken SSO flow.
    """
    if auth_client.is_authenticated:
        return LoginResult(already_authenticated=True)

    result = auth_client.login(username, password, return_on_mfa=True)
    if isinstance(result, tuple) and result and result[0] == "needs_mfa":
        return NeedsMfa(mfa_state=result[1])
    return LoginResult(already_authenticated=False)


def resume_login(auth_client: AuthClient, mfa_code: str, mfa_state: Dict[str, Any]) -> None:
    """Complete a pending MFA login. `mfa_state` must come from the `NeedsMfa` this resumes.

    Raises:
        garmy.core.exceptions.AuthError: if the code is wrong, expired, or verification fails.
    """
    auth_client.resume_login(mfa_code, mfa_state)
