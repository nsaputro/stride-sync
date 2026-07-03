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
