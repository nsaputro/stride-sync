"""Single interface to Garmin Connect auth + activity fetch.

Sync and MCP code should never call `garminconnect` directly — see CLAUDE.md, Coding
Conventions. Wrapping it here means a future library swap (see PROJECT_PLAN.md's "Known risk:
unofficial Garmin auth breakage") is a one-file change — which is exactly what happened here.
This module used to wrap `garmy`, but three successive fixes on top of it (a corrected
User-Agent, `curl_cffi` TLS-fingerprint impersonation, then a human-like login delay — see
CHANGELOG.md) all failed to get past Garmin's Cloudflare bot challenge on the SSO login.
`python-garminconnect` already implements a 5-strategy cascading login chain (mobile app API /
web widget / full portal, each tried with both `curl_cffi` TLS impersonation and plain
`requests`, falling through any non-credential/non-MFA failure to the next strategy) plus its
own anti-bot-detection timing delays — actively maintained against Garmin's changes, rather than
something this add-on has to keep re-discovering and patching fix-by-fix.

`Garmin.get_activities()` (the activity list) doesn't include distance/pace/cadence — those live
on the per-activity detail endpoint (`get_activity()`, raw `summaryDTO`) and the per-lap splits
endpoint (`get_activity_splits()`, raw `lapDTOs`): the same unofficial, undocumented endpoints
`garmy` used, with identical URL patterns and response shapes, which is why those two field
mappings carried over unchanged from the `garmy`-based implementation without needing to be
re-verified. Field names for the activity *list* response itself (`activityId`, `activityName`,
`activityType`, `startTimeLocal`, `startTimeGMT`, and the training-effect fields) are best-effort
based on the Garmin Connect API conventions already confirmed on those other two endpoints, and
have not yet been verified against a live Garmin account from this environment — see
PROJECT_PLAN.md milestone v0.1's "inspect the resulting SQLite DB by hand" step, which is still
open.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import curl_cffi.requests.exceptions as curl_exceptions
import requests
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

# python-garminconnect's own login()/connectapi() wrap most failures into its own exception
# types (the GarminConnect*Error classes below), but it uses both `curl_cffi` and plain
# `requests` internally depending on which login strategy is active, and a broken network path
# can still surface as one of their raw transport exceptions — caught alongside its own
# exceptions below so every failure mode becomes a clean GarminAuthError/GarminAPIError instead
# of an unhandled traceback.
TRANSPORT_ERRORS = (requests.exceptions.RequestException, curl_exceptions.RequestException)

_MFA_REQUIRED_MARKER_NAME = ".mfa_required"

_MFA_REQUIRED_MESSAGE = (
    "Garmin Connect requires a multi-factor authentication (MFA) code for this account, and no "
    "cached session was found. Run the one-time interactive login (`python3 -m "
    "app.sync.bootstrap_login`, see DOCS.md) — scheduled syncs will then reuse that session, "
    "refreshing it as needed, without requiring MFA again."
)

logger = logging.getLogger(__name__)


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


class GarminAuthError(Exception):
    """Raised when Garmin Connect login fails (bad credentials, MFA required, or SSO broken).

    Deliberately not a subclass of garminconnect's exceptions — callers should never need to
    import garminconnect to handle failures from this client (see module docstring).
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


@dataclass(frozen=True)
class TrainingBaseline:
    """Physiological reference point (see PROJECT_PLAN.md milestone v0.5) for interpreting an
    activity's HR/pace as *effort* rather than raw numbers — see app/db/schema.sql
    `training_baseline` table.
    """

    lactate_threshold_hr: Optional[int]
    lactate_threshold_speed_mps: Optional[float]
    lactate_threshold_pace_sec_per_km: Optional[float]
    race_prediction_5k_seconds: Optional[int]
    race_prediction_10k_seconds: Optional[int]
    race_prediction_half_marathon_seconds: Optional[int]
    race_prediction_marathon_seconds: Optional[int]


@dataclass(frozen=True)
class HrZoneTime:
    """Seconds spent in one heart-rate zone during an activity — the actual training stimulus
    of a run, not just its single average HR. See `activity_hr_zones` table.
    """

    activity_id: int
    zone_number: int
    zone_low_boundary_hr: Optional[int]
    seconds_in_zone: Optional[float]


@dataclass(frozen=True)
class ActivitySample:
    """One point of an activity's fine-grained time-series — see `activity_samples` table."""

    activity_id: int
    sample_index: int
    elapsed_seconds: Optional[float]
    heart_rate: Optional[int]
    speed_mps: Optional[float]
    pace_sec_per_km: Optional[float]
    cadence_spm: Optional[float]
    elevation_meters: Optional[float]
    latitude: Optional[float]
    longitude: Optional[float]


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


def _normalize_activity(list_item: Dict[str, Any], detail: Dict[str, Any]) -> GarminActivity:
    """Merge a `Garmin.get_activities()` list entry with the raw `get_activity()` detail.

    Args:
        list_item: one raw entry from `Garmin.get_activities()`.
        detail: raw JSON from `Garmin.get_activity(activity_id)` — the same
            `/activity-service/activity/{id}` endpoint `garmy` used, so the same `summaryDTO`
            shape applies unchanged.
    """
    summary_dto: Dict[str, Any] = detail.get("summaryDTO", {}) or {}
    speed = summary_dto.get("averageSpeed")
    activity_type = list_item.get("activityType") or {}

    return GarminActivity(
        activity_id=list_item["activityId"],
        activity_name=list_item.get("activityName") or "",
        activity_type=activity_type.get("typeKey") or "",
        start_time_local=list_item.get("startTimeLocal") or "",
        start_time_gmt=list_item.get("startTimeGMT") or "",
        duration_seconds=list_item.get("duration") or summary_dto.get("duration"),
        moving_duration_seconds=list_item.get("movingDuration")
        or summary_dto.get("movingDuration"),
        distance_meters=summary_dto.get("distance"),
        average_speed_mps=speed,
        average_pace_sec_per_km=_pace_sec_per_km(speed),
        average_hr=list_item.get("averageHR") or summary_dto.get("averageHR"),
        max_hr=list_item.get("maxHR") or summary_dto.get("maxHR"),
        average_cadence_spm=summary_dto.get("averageRunningCadenceInStepsPerMinute"),
        max_cadence_spm=summary_dto.get("maxRunningCadenceInStepsPerMinute"),
        elevation_gain_meters=summary_dto.get("elevationGain"),
        elevation_loss_meters=summary_dto.get("elevationLoss"),
        calories=summary_dto.get("calories"),
        aerobic_training_effect=list_item.get("aerobicTrainingEffect")
        or summary_dto.get("aerobicTrainingEffect"),
        anaerobic_training_effect=list_item.get("anaerobicTrainingEffect")
        or summary_dto.get("anaerobicTrainingEffect"),
        training_effect_label=list_item.get("trainingEffectLabel") or "",
        activity_training_load=list_item.get("activityTrainingLoad")
        or summary_dto.get("activityTrainingLoad"),
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


def _normalize_training_baseline(
    threshold: Dict[str, Any], predictions: Dict[str, Any]
) -> TrainingBaseline:
    """Merge `Client.get_lactate_threshold(latest=True)` + `Client.get_race_predictions()`.

    Neither endpoint is normalized by `python-garminconnect` itself (both return raw
    `connectapi()` JSON) — field names below are inferred from the wider Garmin Connect tooling
    ecosystem, not yet confirmed against a live account (see PROJECT_PLAN.md milestone v0.5).
    `_get()`'s multi-candidate-key lookup means a wrong guess degrades to `None`, not a crash.
    """
    speed_and_hr = threshold.get("speed_and_heart_rate") or {}
    speed = speed_and_hr.get("speed")

    return TrainingBaseline(
        lactate_threshold_hr=speed_and_hr.get("heartRate"),
        lactate_threshold_speed_mps=speed,
        lactate_threshold_pace_sec_per_km=_pace_sec_per_km(speed),
        race_prediction_5k_seconds=_get(predictions, "raceTime5K", "raceTime5k"),
        race_prediction_10k_seconds=_get(predictions, "raceTime10K", "raceTime10k"),
        race_prediction_half_marathon_seconds=_get(
            predictions, "raceTimeHalfMarathon", "raceTimeHalf"
        ),
        race_prediction_marathon_seconds=_get(predictions, "raceTimeMarathon"),
    )


def _normalize_hr_zones(activity_id: int, raw: Any) -> List[HrZoneTime]:
    """Convert `Client.get_activity_hr_in_timezones(activity_id)`'s raw list into `HrZoneTime`s.

    Best-effort field mapping, same caveat as `_normalize_training_baseline` — see
    PROJECT_PLAN.md milestone v0.5. Any shape other than a list of zone dicts (or a zone dict
    missing its zone number) yields an empty/partial result rather than raising, since not every
    activity has HR zone data (e.g. no HR strap that day).
    """
    zones = raw if isinstance(raw, list) else []
    result = []
    for entry in zones:
        if not isinstance(entry, dict):
            continue
        zone_number = _get(entry, "zoneNumber")
        if zone_number is None:
            continue
        result.append(
            HrZoneTime(
                activity_id=activity_id,
                zone_number=int(zone_number),
                zone_low_boundary_hr=_get(entry, "zoneLowBoundary"),
                seconds_in_zone=_get(entry, "secsInZone"),
            )
        )
    return result


_SAMPLE_METRIC_KEYS: Dict[str, tuple] = {
    "elapsed_seconds": ("sumElapsedDuration", "directElapsedDuration"),
    "heart_rate": ("directHeartRate",),
    "speed_mps": ("directSpeed",),
    "elevation_meters": ("directElevation",),
    "latitude": ("directLatitude",),
    "longitude": ("directLongitude",),
    "cadence_spm": ("directRunCadence", "directDoubleCadence"),
}


def _normalize_samples(activity_id: int, raw: Dict[str, Any]) -> List[ActivitySample]:
    """Convert `Client.get_activity_details(activity_id)`'s columnar chart data into
    `ActivitySample`s (one per elapsed-time point).

    Garmin's raw shape here is index-mapped, not keyed: `metricDescriptors` maps a metric name
    (e.g. "directHeartRate") to a position in each `activityDetailMetrics` entry's flat `metrics`
    list — so every activity's response can use a different column order/subset depending on
    what its recording device captured. Best-effort field mapping, same caveat as
    `_normalize_training_baseline` — see PROJECT_PLAN.md milestone v0.5. A wrong or missing key
    degrades to `None` for that field, not a crash; a malformed/empty response yields `[]`.
    """
    descriptors = raw.get("metricDescriptors") or []
    key_to_index: Dict[str, int] = {
        d["key"]: d["metricsIndex"]
        for d in descriptors
        if isinstance(d, dict) and "key" in d and "metricsIndex" in d
    }

    field_index: Dict[str, Optional[int]] = {}
    for field, candidate_keys in _SAMPLE_METRIC_KEYS.items():
        field_index[field] = next(
            (key_to_index[key] for key in candidate_keys if key in key_to_index), None
        )

    def _value(values: List[Any], field: str) -> Any:
        index = field_index[field]
        if index is None or index >= len(values):
            return None
        return values[index]

    samples: List[ActivitySample] = []
    for sample_index, entry in enumerate(raw.get("activityDetailMetrics") or []):
        if not isinstance(entry, dict):
            continue
        values = entry.get("metrics") or []
        speed = _value(values, "speed_mps")
        samples.append(
            ActivitySample(
                activity_id=activity_id,
                sample_index=sample_index,
                elapsed_seconds=_value(values, "elapsed_seconds"),
                heart_rate=_value(values, "heart_rate"),
                speed_mps=speed,
                pace_sec_per_km=_pace_sec_per_km(speed),
                cadence_spm=_value(values, "cadence_spm"),
                elevation_meters=_value(values, "elevation_meters"),
                latitude=_value(values, "latitude"),
                longitude=_value(values, "longitude"),
            )
        )
    return samples


class GarminClient:
    """Authenticates against Garmin Connect and fetches activity data.

    Every call that reaches Garmin's unofficial API is wrapped so failures surface as
    GarminAuthError/GarminAPIError — never a silently empty result (CLAUDE.md: "Fail loud").
    """

    def __init__(self, username: str, password: str, token_dir: Optional[str] = None) -> None:
        self._username = username
        self._password = password
        # token_dir persists session tokens to disk (defaults under /data — see
        # Settings.garmin_token_dir) so a session survives process restarts. This is what makes
        # MFA accounts workable at all: see login()'s docstring below and
        # app/sync/bootstrap_login.py for the one-time interactive login that populates it.
        self._token_dir = token_dir
        # No return_on_mfa/prompt_mfa: python-garminconnect's own login() then raises
        # GarminConnectAuthenticationError("MFA Required but no prompt_mfa mechanism supplied")
        # directly when MFA is required and no cached session exists — exactly the clear,
        # actionable failure this headless, non-interactive client wants (see login() below).
        self._garmin = Garmin(email=username, password=password)

    def login(self) -> None:
        """Authenticate against Garmin Connect, preferring a cached session.

        Tries loading a cached session directly first — a plain local file read, no network —
        before deciding whether a fresh login is even worth attempting. This has to be a
        separate step from just calling `Garmin.login(tokenstore=...)` unconditionally: that
        call bundles "try cached tokens" and "fall back to a fresh credentialed login" into one
        all-or-nothing method, and a fresh login always re-runs the full login chain from
        scratch, which would re-trigger MFA on every call for accounts that require it —
        unworkable for a service that logs in on every scheduled sync. Splitting the cheap,
        local "is there already a usable session" check out from the network-hitting fresh
        login means the marker check below can gate only the latter.

        Once a fresh login has revealed that this account needs MFA, every subsequent call
        fails fast locally (see `_MFA_REQUIRED_MARKER_NAME`) instead of repeating a fresh login
        attempt every `sync_interval_hours` forever — that attempt cannot succeed without the
        one-time bootstrap anyway, and retrying it against Garmin's unofficial API on a fixed
        schedule is exactly the "auto-retry storm" PROJECT_PLAN.md's known-risk section warns
        could get the account flagged for suspicious activity. Because the cached-session check
        above always runs first, the marker doesn't block noticing that a session now exists
        (e.g. once bootstrap_login.py or the web UI completes) — only the network fresh-login
        attempt is gated, not the local file check.

        Raises:
            GarminAuthError: on bad credentials, required MFA with no cached session, or any
                other auth failure (including the SSO-flow breakage described in
                PROJECT_PLAN.md's known risk).
        """
        if self._token_dir:
            try:
                self._garmin.client.load(self._token_dir)
                if self._garmin.client.is_authenticated:
                    self._clear_mfa_required_marker()
                    return
            except Exception:  # noqa: BLE001 - anything here just means "no cached session yet"
                pass

        if self._mfa_required_marker_set():
            raise GarminAuthError(_MFA_REQUIRED_MESSAGE)

        try:
            mfa_status, _legacy_token = self._garmin.login(tokenstore=self._token_dir)
        except GarminConnectAuthenticationError as exc:
            if "mfa" in str(exc).lower():
                self._set_mfa_required_marker()
                raise GarminAuthError(_MFA_REQUIRED_MESSAGE) from exc
            raise GarminAuthError(f"Garmin Connect login failed: {exc}") from exc
        except GarminConnectTooManyRequestsError as exc:
            raise GarminAuthError(
                f"Garmin Connect rate-limited the login attempt: {exc}"
            ) from exc
        except GarminConnectConnectionError as exc:
            raise GarminAuthError(f"Could not reach Garmin Connect to login: {exc}") from exc
        except TRANSPORT_ERRORS as exc:
            raise GarminAuthError(
                f"Could not reach Garmin Connect to login: {describe_transport_error(exc)}"
            ) from exc

        if mfa_status == "needs_mfa":
            # Shouldn't happen given no return_on_mfa/prompt_mfa was configured above (the
            # library raises GarminConnectAuthenticationError instead) — guarded anyway.
            self._set_mfa_required_marker()
            raise GarminAuthError(_MFA_REQUIRED_MESSAGE)

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
            items = self._garmin.get_activities(limit=limit)
        except (GarminConnectConnectionError, GarminConnectTooManyRequestsError) as exc:
            raise GarminAPIError(f"Failed to fetch activity list: {exc}") from exc
        except TRANSPORT_ERRORS as exc:
            raise GarminAPIError(
                f"Could not reach Garmin Connect to list activities: "
                f"{describe_transport_error(exc)}"
            ) from exc

        activities: List[GarminActivity] = []
        for item in items or []:
            activity_id = item["activityId"]
            detail = self._fetch_activity_detail(activity_id)
            activities.append(_normalize_activity(item, detail))
        return activities

    def fetch_activity_laps(self, activity_id: int) -> List[GarminLap]:
        """Fetch per-lap splits for one activity (pace/cadence/HR broken down over time).

        Raises:
            GarminAPIError: if the splits request fails.
        """
        try:
            raw = self._garmin.get_activity_splits(str(activity_id))
        except (GarminConnectConnectionError, GarminConnectTooManyRequestsError) as exc:
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

    def fetch_training_baseline(self) -> Optional[TrainingBaseline]:
        """Fetch the athlete's current lactate threshold + race predictions (see
        PROJECT_PLAN.md milestone v0.5) — the reference point that turns a raw HR/pace number
        into an effort level.

        Unlike every other `fetch_*` method on this class, a failure here logs a warning and
        returns `None` instead of raising: not every Garmin device/account exposes this data
        (e.g. non-running-focused watches), and there's no clean way to distinguish "this
        account doesn't have this data" from "a request failed" without live-account testing —
        so this supplementary data is always best-effort and never fails the sync as a whole.
        """
        try:
            threshold = self._garmin.get_lactate_threshold(latest=True) or {}
            predictions = self._garmin.get_race_predictions() or {}
        except Exception as exc:  # noqa: BLE001 - see docstring: deliberately non-fatal
            logger.warning("Could not fetch training baseline (non-fatal): %s", exc)
            return None
        return _normalize_training_baseline(threshold, predictions)

    def fetch_activity_hr_zones(self, activity_id: int) -> List[HrZoneTime]:
        """Fetch seconds-in-each-HR-zone for one activity (see PROJECT_PLAN.md milestone v0.5).

        Best-effort, same reasoning as `fetch_training_baseline`: not every activity has HR zone
        data (e.g. no HR strap that day), so a failure here is logged and treated as "no zone
        data for this activity" rather than failing the whole sync.
        """
        try:
            raw = self._garmin.get_activity_hr_in_timezones(str(activity_id))
        except Exception as exc:  # noqa: BLE001 - see docstring: deliberately non-fatal
            logger.warning(
                "Could not fetch HR zones for activity %s (non-fatal): %s", activity_id, exc
            )
            return []
        return _normalize_hr_zones(activity_id, raw)

    def fetch_activity_samples(self, activity_id: int) -> List[ActivitySample]:
        """Fetch the fine-grained time-series for one activity (see PROJECT_PLAN.md milestone
        v0.5). Best-effort, same reasoning as `fetch_activity_hr_zones`.
        """
        try:
            raw = self._garmin.get_activity_details(str(activity_id))
        except Exception as exc:  # noqa: BLE001 - see docstring: deliberately non-fatal
            logger.warning(
                "Could not fetch time-series samples for activity %s (non-fatal): %s",
                activity_id,
                exc,
            )
            return []
        return _normalize_samples(activity_id, raw if isinstance(raw, dict) else {})

    def _fetch_activity_detail(self, activity_id: int) -> Dict[str, Any]:
        try:
            detail = self._garmin.get_activity(str(activity_id))
        except (GarminConnectConnectionError, GarminConnectTooManyRequestsError) as exc:
            raise GarminAPIError(
                f"Failed to fetch detail for activity {activity_id}: {exc}"
            ) from exc
        except TRANSPORT_ERRORS as exc:
            raise GarminAPIError(
                f"Could not reach Garmin Connect to fetch detail for activity {activity_id}: "
                f"{describe_transport_error(exc)}"
            ) from exc
        return detail if isinstance(detail, dict) else {}
