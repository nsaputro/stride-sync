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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from garmy import APIClient, AuthClient
from garmy.core.exceptions import APIError, AuthError

# garmy's SSO login flow doesn't wrap transport-level failures (connection errors, proxy
# errors, timeouts) in its own exception types — a broken network path to Garmin surfaces as a
# raw `requests` exception. Caught alongside garmy's own AuthError/APIError below so every
# failure mode described in PROJECT_PLAN.md's "known risk" section becomes a clean
# GarminAuthError/GarminAPIError instead of an unhandled traceback.
_TRANSPORT_ERRORS = (requests.exceptions.RequestException,)

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

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._auth_client = AuthClient()
        self._api_client = APIClient(auth_client=self._auth_client)

    def login(self) -> None:
        """Authenticate against Garmin Connect.

        Raises:
            GarminAuthError: on bad credentials, required MFA, or any other auth failure
                (including the SSO-flow breakage described in PROJECT_PLAN.md's known risk).
        """
        try:
            result = self._api_client.login(self._username, self._password)
        except AuthError as exc:
            raise GarminAuthError(f"Garmin Connect login failed: {exc}") from exc
        except _TRANSPORT_ERRORS as exc:
            raise GarminAuthError(f"Could not reach Garmin Connect to login: {exc}") from exc

        # garmy doesn't raise when MFA is required and no prompt_mfa callback was given (we
        # never pass one) — it returns ("needs_mfa", state) instead. Left unchecked, this falls
        # through to the generic "did not return valid tokens" error below, hiding the actual,
        # actionable cause.
        if isinstance(result, tuple) and result and result[0] == "needs_mfa":
            raise GarminAuthError(
                "Garmin Connect requires a multi-factor authentication (MFA) code for this "
                "account. StrideSync runs headless and cannot answer an interactive MFA "
                "prompt — use a Garmin account with MFA disabled, or disable MFA for this "
                "account in Garmin Connect account settings."
            )

        if not self._api_client.is_authenticated:
            raise GarminAuthError("Garmin Connect login did not return valid tokens.")

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
        except _TRANSPORT_ERRORS as exc:
            raise GarminAPIError(
                f"Could not reach Garmin Connect to list activities: {exc}"
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
        except _TRANSPORT_ERRORS as exc:
            raise GarminAPIError(
                f"Could not reach Garmin Connect to fetch laps for activity {activity_id}: {exc}"
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
        except _TRANSPORT_ERRORS as exc:
            raise GarminAPIError(
                f"Could not reach Garmin Connect to fetch detail for activity {activity_id}: {exc}"
            ) from exc
        return detail if isinstance(detail, dict) else {}
