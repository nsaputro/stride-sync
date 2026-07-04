"""Single interface to Garmin Connect auth + activity fetch.

Sync and MCP code should never call `garmy` (or a fallback library) directly — see CLAUDE.md,
Coding Conventions. Wrapping it here means a future library swap (see PROJECT_PLAN.md's "Known
risk: unofficial Garmin auth breakage") is a one-file change.

garmy's built-in `metrics.get('activities').list()` only returns duration, heart rate, training
effect/load, stress, and respiration — no distance, pace, or cadence (see ActivitySummary in
garmy's source). Those fields live on the per-activity detail endpoint
(`/activity-service/activity/{id}`, `summaryDTO`) and the per-lap splits endpoint
(`/activity-service/activity/{id}/splits`, `lapDTOs`), both unofficial and undocumented, called
here via `APIClient.connectapi()`. Field names are best-effort based on the shape used across the
existing Garmin Connect tooling ecosystem (e.g. python-garminconnect) and have not yet been
verified against a live Garmin account from this environment — see PROJECT_PLAN.md milestone
v0.1's "inspect the resulting SQLite DB by hand" step, which is still open.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import curl_cffi.requests.exceptions as curl_exceptions
import requests
from garmy import APIClient, AuthClient
from garmy.core.exceptions import APIError, AuthError

from app.sync import garmy_tls_impersonation, garmy_ua_override

garmy_ua_override.apply()
garmy_tls_impersonation.apply()

# garmy's SSO login flow doesn't wrap transport-level failures (connection errors, proxy
# errors, timeouts) in its own exception types — a broken network path to Garmin surfaces as a
# raw `requests` exception. Caught alongside garmy's own AuthError/APIError below so every
# failure mode described in PROJECT_PLAN.md's "known risk" section becomes a clean
# GarminAuthError/GarminAPIError instead of an unhandled traceback. Includes curl_cffi's own
# RequestException too (not a subclass of requests' one) since garmy_tls_impersonation.py routes
# the SSO login flow specifically through curl_cffi — see that module's docstring.
TRANSPORT_ERRORS = (requests.exceptions.RequestException, curl_exceptions.RequestException)


def describe_transport_error(exc: Exception) -> str:
    """Render a transport error with diagnostic detail beyond the bare exception message.

    For an `HTTPError` (raised via `response.raise_for_status()`), the bare message is just
    "<status> Client Error: ... for url: ...", which can't distinguish a Cloudflare-level block
    (typically has a `cf-ray` header and an HTML challenge/block-page body) from a plain
    application-level rejection from Garmin itself — a distinction worth knowing before deciding
    whether a fix even belongs in this codebase at all (see PROJECT_PLAN.md's "known risk"
    section). Selected headers plus a short body snippet are appended when a response is
    available; never includes request headers/cookies/credentials.
    """
    detail = str(exc)
    response = getattr(exc, "response", None)
    if response is None:
        return detail

    extra = []
    server = response.headers.get("server")
    if server:
        extra.append(f"server={server}")
    cf_ray = response.headers.get("cf-ray")
    if cf_ray:
        extra.append(f"cf-ray={cf_ray}")
    cf_mitigated = response.headers.get("cf-mitigated")
    if cf_mitigated:
        extra.append(f"cf-mitigated={cf_mitigated}")
    body_snippet = (response.text or "").strip()[:200].replace("\n", " ")
    if body_snippet:
        extra.append(f"body={body_snippet!r}")

    if not extra:
        return detail
    return f"{detail} ({', '.join(extra)})"


_MFA_REQUIRED_MARKER_NAME = ".mfa_required"

_MFA_REQUIRED_MESSAGE = (
    "Garmin Connect requires a multi-factor authentication (MFA) code for this account, and no "
    "cached session was found. Run the one-time interactive login (`python3 -m "
    "app.sync.bootstrap_login`, see DOCS.md) — scheduled syncs will then reuse that session, "
    "refreshing it as needed, without requiring MFA again."
)

logger = logging.getLogger(__name__)


class GarminAuthError(Exception):
    """Raised when Garmin Connect login fails (bad credentials, MFA required, or SSO broken).

    Deliberately not a subclass of garmy's exceptions — callers should never need to import
    garmy to handle failures from this client (see module docstring).
    """


class GarminAPIError(Exception):
    """Raised when an authenticated Garmin Connect API request fails."""


@dataclass(frozen=True)
class GarminActivity:
    """Normalized activity record — see app/db/schema.sql `activities` table."""

    activity_id: int
    activity_name: str
    activity_type: str
    start_time_local: str
    start_time_gmt: str
    duration_seconds: Optional[float]
    moving_duration_seconds: Optional[float]
    distance_meters: Optional[float]
    average_speed_mps: Optional[float]
    average_pace_sec_per_km: Optional[float]
    average_hr: Optional[int]
    max_hr: Optional[int]
    average_cadence_spm: Optional[float]
    max_cadence_spm: Optional[float]
    elevation_gain_meters: Optional[float]
    elevation_loss_meters: Optional[float]
    calories: Optional[float]
    aerobic_training_effect: Optional[float]
    anaerobic_training_effect: Optional[float]
    training_effect_label: str
    activity_training_load: Optional[float]


@dataclass(frozen=True)
class GarminLap:
    """Normalized per-lap record — see app/db/schema.sql `activity_metrics` table."""

    activity_id: int
    lap_index: int
    start_time_gmt: Optional[str]
    duration_seconds: Optional[float]
    distance_meters: Optional[float]
    average_speed_mps: Optional[float]
    pace_sec_per_km: Optional[float]
    average_hr: Optional[int]
    max_hr: Optional[int]
    average_cadence_spm: Optional[float]
    max_cadence_spm: Optional[float]


def _pace_sec_per_km(speed_mps: Optional[float]) -> Optional[float]:
    """Convert average speed (m/s) to pace (seconds per km). None if speed is missing/zero."""
    if not speed_mps:
        return None
    return 1000.0 / speed_mps


def _get(source: Dict[str, Any], *keys: str) -> Any:
    """Return the first present key's value from a raw Garmin API response dict."""
    for key in keys:
        if key in source:
            return source[key]
    return None


def _normalize_activity(summary: Any, detail: Dict[str, Any]) -> GarminActivity:
    """Merge garmy's ActivitySummary with the raw `/activity-service/activity/{id}` detail.

    Args:
        summary: garmy ActivitySummary from `metrics.get('activities').list()`.
        detail: raw JSON from `connectapi(f"/activity-service/activity/{activity_id}")`.
    """
    summary_dto: Dict[str, Any] = detail.get("summaryDTO", {}) or {}
    speed = summary_dto.get("averageSpeed")

    return GarminActivity(
        activity_id=summary.activity_id,
        activity_name=summary.activity_name,
        activity_type=summary.activity_type_name,
        start_time_local=summary.start_time_local,
        start_time_gmt=summary.start_time_gmt,
        duration_seconds=summary.duration or summary_dto.get("duration"),
        moving_duration_seconds=summary.moving_duration or summary_dto.get("movingDuration"),
        distance_meters=summary_dto.get("distance"),
        average_speed_mps=speed,
        average_pace_sec_per_km=_pace_sec_per_km(speed),
        average_hr=summary.average_hr or summary_dto.get("averageHR"),
        max_hr=summary.max_hr or summary_dto.get("maxHR"),
        average_cadence_spm=summary_dto.get("averageRunningCadenceInStepsPerMinute"),
        max_cadence_spm=summary_dto.get("maxRunningCadenceInStepsPerMinute"),
        elevation_gain_meters=summary_dto.get("elevationGain"),
        elevation_loss_meters=summary_dto.get("elevationLoss"),
        calories=summary_dto.get("calories"),
        aerobic_training_effect=summary.aerobic_training_effect,
        anaerobic_training_effect=summary.anaerobic_training_effect,
        training_effect_label=summary.training_effect_label,
        activity_training_load=summary.activity_training_load,
    )


def _normalize_lap(activity_id: int, lap_index: int, raw: Dict[str, Any]) -> GarminLap:
    """Convert one raw `lapDTOs` entry from the splits endpoint into a GarminLap."""
    speed = _get(raw, "averageSpeed")

    return GarminLap(
        activity_id=activity_id,
        lap_index=lap_index,
        start_time_gmt=_get(raw, "startTimeGMT"),
        duration_seconds=_get(raw, "duration"),
        distance_meters=_get(raw, "distance"),
        average_speed_mps=speed,
        pace_sec_per_km=_pace_sec_per_km(speed),
        average_hr=_get(raw, "averageHR"),
        max_hr=_get(raw, "maxHR"),
        average_cadence_spm=_get(raw, "averageRunCadence"),
        max_cadence_spm=_get(raw, "maxRunCadence"),
    )


class GarminClient:
    """Authenticates against Garmin Connect and fetches activity data.

    Every call that reaches Garmin's unofficial API is wrapped so failures surface as
    GarminAuthError/GarminAPIError — never a silently empty result (CLAUDE.md: "Fail loud").
    """

    def __init__(self, username: str, password: str, token_dir: Optional[str] = None) -> None:
        self._username = username
        self._password = password
        self._token_dir = token_dir
        # token_dir persists OAuth1/OAuth2 tokens to disk (defaults under /data — see
        # Settings.garmin_token_dir) so a session survives process restarts. This is what makes
        # MFA accounts workable at all: see login()'s refresh-before-login preference below and
        # app/sync/bootstrap_login.py for the one-time interactive login that populates it.
        self._auth_client = AuthClient(token_dir=token_dir)
        self._api_client = APIClient(auth_client=self._auth_client)

    def login(self) -> None:
        """Authenticate against Garmin Connect, preferring a cached/refreshed session.

        A fresh login always re-runs the full SSO flow from scratch, which re-triggers MFA on
        every call for accounts that require it — unworkable for a service that logs in on
        every scheduled sync. So this checks for (and refreshes) an existing cached session
        first, from a previous login or bootstrap_login.py run, and only falls back to a fresh
        login if there is no usable session yet.

        Once a fresh login has revealed that this account needs MFA, every subsequent call
        fails fast locally (see `_MFA_REQUIRED_MARKER_NAME`) instead of repeating a fresh SSO
        login attempt every `sync_interval_hours` forever — that attempt cannot succeed without
        the one-time bootstrap anyway, and retrying it against Garmin's unofficial API on a
        fixed schedule is exactly the "auto-retry storm" PROJECT_PLAN.md's known-risk section
        warns could get the account flagged for suspicious activity. The marker is cleared
        automatically the next time a session is found valid (i.e. after bootstrap_login.py or
        the web UI completes).

        Raises:
            GarminAuthError: on bad credentials, required MFA with no cached session, or any
                other auth failure (including the SSO-flow breakage described in
                PROJECT_PLAN.md's known risk).
        """
        if self._auth_client.is_authenticated:
            self._clear_mfa_required_marker()
            return  # valid cached session — nothing to do

        if self._auth_client.needs_refresh:
            try:
                self._auth_client.refresh_tokens()
                self._clear_mfa_required_marker()
                return
            except AuthError:
                pass  # cached session itself was revoked/invalid — fall through to fresh login
            except TRANSPORT_ERRORS as exc:
                raise GarminAuthError(
                    f"Could not reach Garmin Connect to refresh session: "
                    f"{describe_transport_error(exc)}"
                ) from exc

        if self._mfa_required_marker_set():
            raise GarminAuthError(_MFA_REQUIRED_MESSAGE)

        try:
            result = self._api_client.login(self._username, self._password)
        except AuthError as exc:
            raise GarminAuthError(f"Garmin Connect login failed: {exc}") from exc
        except TRANSPORT_ERRORS as exc:
            raise GarminAuthError(
                f"Could not reach Garmin Connect to login: {describe_transport_error(exc)}"
            ) from exc

        # garmy doesn't raise when MFA is required and no prompt_mfa callback was given (we
        # never pass one) — it returns ("needs_mfa", state) instead. Left unchecked, this falls
        # through to the generic "did not return valid tokens" error below, hiding the actual,
        # actionable cause.
        if isinstance(result, tuple) and result and result[0] == "needs_mfa":
            self._set_mfa_required_marker()
            raise GarminAuthError(_MFA_REQUIRED_MESSAGE)

        if not self._auth_client.is_authenticated:
            raise GarminAuthError("Garmin Connect login did not return valid tokens.")

        self._clear_mfa_required_marker()

    def _mfa_marker_path(self) -> Optional[str]:
        if not self._token_dir:
            return None
        return os.path.join(self._token_dir, _MFA_REQUIRED_MARKER_NAME)

    def _mfa_required_marker_set(self) -> bool:
        path = self._mfa_marker_path()
        return bool(path) and os.path.exists(path)

    def _set_mfa_required_marker(self) -> None:
        path = self._mfa_marker_path()
        if not path:
            return
        try:
            os.makedirs(self._token_dir, exist_ok=True)  # type: ignore[arg-type]
            with open(path, "w") as f:
                f.write("MFA required as of the last fresh login attempt.\n")
        except OSError as exc:
            logger.warning("Could not persist MFA-required marker at %s: %s", path, exc)

    def _clear_mfa_required_marker(self) -> None:
        path = self._mfa_marker_path()
        if not path:
            return
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not clear MFA-required marker at %s: %s", path, exc)

    def fetch_recent_activities(self, limit: int = 20) -> List[GarminActivity]:
        """Fetch the most recent activities, with full distance/pace/cadence detail.

        Args:
            limit: Maximum number of activities to fetch, most recent first.

        Raises:
            GarminAPIError: if the activity list or a detail request fails.
        """
        try:
            summaries = self._api_client.metrics.get("activities").list(limit=limit)
        except APIError as exc:
            raise GarminAPIError(f"Failed to fetch activity list: {exc}") from exc
        except TRANSPORT_ERRORS as exc:
            raise GarminAPIError(
                f"Could not reach Garmin Connect to list activities: "
                f"{describe_transport_error(exc)}"
            ) from exc

        activities: List[GarminActivity] = []
        for summary in summaries:
            detail = self._fetch_activity_detail(summary.activity_id)
            activities.append(_normalize_activity(summary, detail))
        return activities

    def fetch_activity_laps(self, activity_id: int) -> List[GarminLap]:
        """Fetch per-lap splits for one activity (pace/cadence/HR broken down over time).

        Raises:
            GarminAPIError: if the splits request fails.
        """
        try:
            raw = self._api_client.connectapi(
                f"/activity-service/activity/{activity_id}/splits"
            )
        except APIError as exc:
            raise GarminAPIError(
                f"Failed to fetch laps for activity {activity_id}: {exc}"
            ) from exc
        except TRANSPORT_ERRORS as exc:
            raise GarminAPIError(
                f"Could not reach Garmin Connect to fetch laps for activity {activity_id}: "
                f"{describe_transport_error(exc)}"
            ) from exc

        lap_dtos = (raw or {}).get("lapDTOs", [])
        return [
            _normalize_lap(activity_id, index, lap) for index, lap in enumerate(lap_dtos)
        ]

    def _fetch_activity_detail(self, activity_id: int) -> Dict[str, Any]:
        try:
            detail = self._api_client.connectapi(f"/activity-service/activity/{activity_id}")
        except APIError as exc:
            raise GarminAPIError(
                f"Failed to fetch detail for activity {activity_id}: {exc}"
            ) from exc
        except TRANSPORT_ERRORS as exc:
            raise GarminAPIError(
                f"Could not reach Garmin Connect to fetch detail for activity {activity_id}: "
                f"{describe_transport_error(exc)}"
            ) from exc
        return detail if isinstance(detail, dict) else {}
