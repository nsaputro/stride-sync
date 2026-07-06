-- SQLite schema for /data/stridesync.db — see PROJECT_PLAN.md milestone v0.1.
--
-- activities: one row per Garmin activity, normalized from the activity list summary
-- (garmy's ActivitySummary) merged with the full activity detail endpoint (distance, pace,
-- cadence, elevation — not present in the summary). See app/sync/garmin_client.py.
--
-- activity_metrics: per-lap time series (one row per Garmin "split"/lap) giving pace, cadence,
-- and heart rate broken down over the course of an activity, rather than a single average.
--
-- sync_log: outcome of every sync run — success/partial/failed, counts, and error detail — so
-- staleness is never silent (see CLAUDE.md, "Fail loud, not silent").

CREATE TABLE IF NOT EXISTS activities (
    activity_id             INTEGER PRIMARY KEY,
    activity_name           TEXT,
    activity_type           TEXT,
    start_time_local        TEXT NOT NULL,
    start_time_gmt          TEXT,
    duration_seconds        REAL,
    moving_duration_seconds REAL,
    distance_meters         REAL,
    average_speed_mps       REAL,
    average_pace_sec_per_km REAL,
    average_hr              INTEGER,
    max_hr                  INTEGER,
    average_cadence_spm     REAL,
    max_cadence_spm         REAL,
    elevation_gain_meters   REAL,
    elevation_loss_meters   REAL,
    calories                REAL,
    aerobic_training_effect REAL,
    anaerobic_training_effect REAL,
    training_effect_label   TEXT,
    activity_training_load  REAL,
    synced_at               TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_metrics (
    activity_id       INTEGER NOT NULL,
    lap_index         INTEGER NOT NULL,
    start_time_gmt    TEXT,
    duration_seconds  REAL,
    distance_meters   REAL,
    average_speed_mps REAL,
    pace_sec_per_km   REAL,
    average_hr        INTEGER,
    max_hr            INTEGER,
    average_cadence_spm REAL,
    max_cadence_spm   REAL,
    PRIMARY KEY (activity_id, lap_index),
    FOREIGN KEY (activity_id) REFERENCES activities (activity_id)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    status             TEXT NOT NULL,  -- 'success' | 'partial' | 'failed'
    activities_synced  INTEGER NOT NULL DEFAULT 0,
    error_message      TEXT
);

-- training_baseline: the athlete's current physiological reference point (lactate threshold
-- HR/pace, Garmin's own race-time predictions) — see PROJECT_PLAN.md milestone v0.5. A single
-- row, replaced (not appended) on every sync: it's "current state," not a time series. Without
-- this, an activity's average HR/pace has no reference point to judge effort against.
CREATE TABLE IF NOT EXISTS training_baseline (
    id                                     INTEGER PRIMARY KEY CHECK (id = 1),
    synced_at                              TEXT NOT NULL,
    lactate_threshold_hr                   INTEGER,
    lactate_threshold_speed_mps            REAL,
    lactate_threshold_pace_sec_per_km      REAL,
    race_prediction_5k_seconds             INTEGER,
    race_prediction_10k_seconds            INTEGER,
    race_prediction_half_marathon_seconds  INTEGER,
    race_prediction_marathon_seconds       INTEGER
);

-- activity_hr_zones: seconds spent in each Garmin heart-rate zone (1-5) per activity — the
-- actual training stimulus of a run (how much of it was easy vs. threshold effort), not just its
-- single average HR number. See PROJECT_PLAN.md milestone v0.5.
CREATE TABLE IF NOT EXISTS activity_hr_zones (
    activity_id          INTEGER NOT NULL,
    zone_number          INTEGER NOT NULL,
    zone_low_boundary_hr INTEGER,
    seconds_in_zone      REAL,
    PRIMARY KEY (activity_id, zone_number),
    FOREIGN KEY (activity_id) REFERENCES activities (activity_id)
);

-- activity_samples: fine-grained time-series within an activity (pace/HR/cadence/elevation over
-- elapsed time, up to Garmin's own ~2000-point chart-resolution cap) — enables things like
-- cardiac-drift or precise negative-split detection that 1km auto-lap averages hide. See
-- PROJECT_PLAN.md milestone v0.5.
CREATE TABLE IF NOT EXISTS activity_samples (
    activity_id         INTEGER NOT NULL,
    sample_index        INTEGER NOT NULL,
    elapsed_seconds     REAL,
    heart_rate          INTEGER,
    speed_mps           REAL,
    pace_sec_per_km     REAL,
    cadence_spm         REAL,
    elevation_meters    REAL,
    latitude            REAL,
    longitude           REAL,
    temperature_celsius REAL,
    PRIMARY KEY (activity_id, sample_index),
    FOREIGN KEY (activity_id) REFERENCES activities (activity_id)
);

-- daily_wellness: one row per calendar date — sleep, HRV, Garmin's own training-status label,
-- training-readiness score, and resting HR — see PROJECT_PLAN.md milestone v0.12. Unlike
-- `activities` (keyed by Garmin's own activity_id, appended per sync), this is fetched and
-- upserted for a small rolling window of recent dates on every sync (Garmin sometimes finalizes
-- sleep/HRV data a day late), overwriting whatever was stored for that date before. Nullable
-- throughout — not every endpoint/device/account reports every field, and each of the five
-- source endpoints failing independently degrades only its own column(s) to NULL rather than the
-- whole day's row.
CREATE TABLE IF NOT EXISTS daily_wellness (
    calendar_date            TEXT PRIMARY KEY,
    synced_at                TEXT NOT NULL,
    sleep_score              INTEGER,
    sleep_duration_seconds   REAL,
    deep_sleep_seconds       REAL,
    light_sleep_seconds      REAL,
    rem_sleep_seconds        REAL,
    awake_sleep_seconds      REAL,
    hrv_status               TEXT,
    hrv_weekly_avg_ms        REAL,
    hrv_last_night_avg_ms    REAL,
    training_status_label    TEXT,
    training_readiness_score INTEGER,
    resting_hr               INTEGER
);

-- vo2max_history: one row per calendar date, Garmin's own VO2 max estimate (running/cycling) and
-- fitness age — see PROJECT_PLAN.md milestone v0.12. Additive to `training_baseline` (lactate
-- threshold/race predictions), not a replacement: fetched daily (same rolling-window pattern as
-- daily_wellness) rather than "current state only," so a trend over time is possible.
CREATE TABLE IF NOT EXISTS vo2max_history (
    calendar_date   TEXT PRIMARY KEY,
    synced_at       TEXT NOT NULL,
    vo2_max_running REAL,
    vo2_max_cycling REAL,
    fitness_age     INTEGER
);
