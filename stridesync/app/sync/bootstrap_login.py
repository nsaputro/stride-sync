"""One-time interactive login for Garmin accounts with MFA/2FA enabled.

A scheduled sync always calls GarminClient.login(), which prefers a cached/refreshed session
over a fresh login specifically so MFA accounts work at all (see garmin_client.py's login()
docstring) — but that cached session has to come from somewhere the first time. Run this once,
interactively, after the add-on reports "requires MFA... no cached session was found":

    python3 -m app.sync.bootstrap_login

Standalone (docker run):
    docker exec -it <container> python3 -m app.sync.bootstrap_login

Real HA install (via the "Terminal & SSH" add-on):
    ha addons exec <slug> python3 -m app.sync.bootstrap_login

Logs in, prompts for the MFA code Garmin sends you, and persists the resulting session tokens to
`garmin_token_dir` (default `/data/.garmin_tokens`) — the same location every scheduled sync
reads from. Re-run this if a sync ever reports the session was lost (e.g. the underlying token
was itself revoked or expired) and a fresh MFA login is needed again.
"""

from __future__ import annotations

import sys

from garminconnect import Garmin, GarminConnectAuthenticationError

from app.config import Settings
from app.sync import mfa_login
from app.sync.garmin_client import TRANSPORT_ERRORS, describe_transport_error


def main() -> int:
    settings = Settings.from_env()

    if not settings.garmin_username or not settings.garmin_password:
        print("GARMIN_USERNAME and GARMIN_PASSWORD must be set.", file=sys.stderr)
        return 1

    garmin = Garmin(
        email=settings.garmin_username,
        password=settings.garmin_password,
        return_on_mfa=True,
    )

    try:
        result = mfa_login.start_login(garmin, settings.garmin_token_dir)
    except GarminConnectAuthenticationError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return 1
    except TRANSPORT_ERRORS as exc:
        print(f"Could not reach Garmin Connect: {describe_transport_error(exc)}", file=sys.stderr)
        return 1

    if isinstance(result, mfa_login.NeedsMfa):
        print("Garmin sent a multi-factor authentication code to your registered device/email.")
        mfa_code = input("Enter the MFA code: ").strip()
        try:
            mfa_login.resume_login(garmin, mfa_code, settings.garmin_token_dir)
        except GarminConnectAuthenticationError as exc:
            print(f"MFA verification failed: {exc}", file=sys.stderr)
            return 1
        except TRANSPORT_ERRORS as exc:
            print(
                f"Could not reach Garmin Connect: {describe_transport_error(exc)}",
                file=sys.stderr,
            )
            return 1

    if not garmin.client.is_authenticated:
        print("Login did not produce a valid session.", file=sys.stderr)
        return 1

    print(f"Success — session saved to {settings.garmin_token_dir}.")
    print("Scheduled syncs will now reuse (and refresh) this session without requiring MFA again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
