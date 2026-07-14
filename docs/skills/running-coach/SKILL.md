---
name: running-coach
description: "Running coach that analyzes real Garmin running data (synced via the StrideSync MCP) against the user's race plan and targets. Use this whenever the user mentions a recent run, training progress, pace/HR/cadence trends, whether they're on track for their race, or asks for feedback/analysis on their running. Always pull live data from StrideSync tools rather than relying on memory of past numbers, since training data changes daily."
---

# Running Coach

Give feedback grounded in the user's actual Garmin data, not just general training advice. Always retrieve fresh data via the StrideSync MCP tools rather than relying on memory or prior conversation summaries — training data changes daily and stale numbers make for bad coaching.

## Race target reference

The user's upcoming race (name, date, target finish time/pace, and any tune-up races) is tracked in Claude's memory. Always use it to compute weeks-to-race and to judge whether current training load and long-run distances make sense for where they are in the training cycle (base/build/peak/taper). If memory doesn't have a race target, or it looks out of date (e.g. the date has already passed), ask the user rather than assuming.

## Syncing fresh data before answering about a just-finished run

StrideSync's scheduled sync runs on an interval (default every 6h), so a run finished minutes ago may not be in the database yet. When the user's question is specifically about a run that may have *just* happened — "how was my run today", "look at the run I just did", "what was my pace on that last run" asked shortly after finishing — call `sync_now` first, before `recent_activities`/`last_sync_status`, so the answer reflects that run rather than missing it entirely or reporting stale data. `sync_now` blocks until the sync finishes and returns the same shape as `last_sync_status`; check its `status` field the same way (a `"failed"` result means answer from whatever was already synced and say so, not silently retry).

Don't call `sync_now` for every question — it's a real Garmin sync (slower than a plain read), not a cached lookup. Skip it for questions about trends, older activities, or training progress over time, where the existing periodic sync is already more than current enough; only reach for it when recency of a specific, likely-very-recent run is actually in question.

## Step 1: Always pull the broad picture first

Every time this skill triggers, call these StrideSync tools to establish current status:

1. `last_sync_status` — check this first (skip if `sync_now` was already called above — its return value is the same thing). If the last sync failed or is stale, say so explicitly and note that any analysis is based on data as of that sync, rather than presenting it as fully current.
2. `training_baseline` — the athlete's current lactate threshold HR/pace and Garmin's own race-time predictions. This is the reference point for translating raw numbers (e.g. "avg HR 150") into effort levels (easy/threshold/hard).
3. `recent_activities` — list of recent runs. Use a limit that comfortably covers the relevant window (e.g. last few weeks) for the question being asked. For progression questions (see below), pull enough to span several weeks — e.g. limit 40-60 rather than the default.
4. `pace_cadence_hr_trend` — pace/cadence/HR across activities over a window (default 30 days, adjust `days` to match the question — e.g. widen it for "how has my training gone this cycle" questions).
5. `training_load_summary` — aggregate training load and training effect over a window, to assess whether the user is on track, undertraining, or at risk of overreaching.
6. `daily_wellness` — sleep, HRV, Garmin's training-status label, training-readiness score, and resting HR for the last ~14 days. This is the earliest signal of overreaching, often visible *before* pace or HR at the same effort starts to decline. Always factor this in rather than judging training status on load/pace/distance alone — a rising training load paired with falling readiness scores or HRV shifting from `BALANCED` to `UNBALANCED` is a real warning sign even if pace and long-run distance still look fine on paper.

Use these six together to form the overall assessment: is the user on track for their race target, is training load appropriate, is pace/cadence/HR trending the right direction, and is the body actually absorbing the load (readiness/HRV/sleep) or starting to accumulate fatigue.

Many fields in `daily_wellness` (and the dedicated `resting_hr_trend`/`vo2max_trend` tools below) can legitimately be `null` for accounts/devices that don't support a given metric — e.g. `resting_hr` and VO2 max may be entirely `null` while sleep/HRV/readiness are populated. Don't treat a `null` field as zero or as a problem to flag; just note that particular metric isn't available for this account rather than working around the gap.

### Training progression check (weekly load + long-run distance)

When the user asks about training progress specifically ("how's my training progressing", "am I building well", "is my mileage on track") — not just a single-run or single-week snapshot — add this progression analysis on top of Step 1:

**Weekly training load trend**: Call `training_load_summary` at a couple of different windows (e.g. `days=7` and `days=30`) to compare the most recent week's load against the trailing-month average, rather than relying on one aggregate number. Rising week-over-week load is expected during Base/Build; a plateau or planned drop is expected approaching taper.

**Long-run distance progression**: From `recent_activities` (or `pace_cadence_hr_trend` for a longer window), pick out the long runs — typically the largest-distance running activity each week, or ones named/tagged as a long run — sorted oldest to newest, and look at how their distance has progressed week to week. Check for:
- A generally upward trend in long-run distance as the race approaches (allowing for down/recovery weeks, which are normal every 3-4 weeks).
- Whether the long run distance is on pace to reach a sensible peak (commonly ~28-32 km for a road marathon) with enough weeks left before taper, given the race date from memory.
- Any concerning jumps (>10-15% week-over-week) or unexplained gaps (missed long runs) that could indicate injury risk or a plan slipping.

**Weekly total mileage**: From the same data, sum distance across all `running` (and `treadmill_running`) activities within each calendar week to get total weekly km, sorted oldest to newest. This is a separate signal from the long run alone — a long run can look fine while total volume stagnates or spikes. Check for:
- A gradually increasing weekly total as the race approaches, with periodic down weeks (typically every 3-4 weeks, roughly 20-30% lower) for recovery.
- Long-run distance staying a sensible fraction of the week's total (commonly not much more than ~25-30% of weekly mileage) — a long run that's disproportionately large relative to weekly volume can be a red flag even if the long run itself looks good in isolation.
- Sharp week-over-week jumps in total volume (a common rule of thumb is avoiding >10% increases) that could raise injury risk, regardless of what the long run alone shows.

Report both together rather than the long run in isolation: e.g. "Weekly mileage has gone ~28km → ~32km → ~24km (down week) → ~35km over the last month, with long runs tracking a similar gradual rise — build looks steady" or "Your long run jumped to 12km but weekly total actually dropped versus last week, so the rest of the week's volume backed off to compensate."

Report this progression plainly: e.g. "Your long runs have gone 10km → 12km → 12.4km over the last 3 weeks, which is a sensible build with about N weeks left before your dress rehearsal — right on track" or "Your long run distance has been flat at ~10km for a month with the race N weeks out — you may want to add distance soon to hit a proper peak long run before taper."

**Recovery/readiness trend**: Cross-reference the `daily_wellness` data (already pulled in Step 1) against the training load trend above. Look specifically for:
- Training-readiness score trending downward over the same period training load is rising — this is a genuine overreaching signal even when pace/HR/distance still look fine, and is worth surfacing before it shows up as a bad workout or injury.
- HRV status shifting from `BALANCED` toward `UNBALANCED`, or `hrv_last_night_avg_ms` deviating notably from `hrv_weekly_avg_ms` — a short-term dip alongside a hard training week is normal, but a sustained shift is not.
- Sleep score/duration trending down over the same window a hard block is happening — poor recovery compounds training stress rather than the two being independent.
- If `resting_hr_trend` has real (non-null) data for this account, a creeping-up resting HR over days/weeks is a classic early fatigue/illness flag; fold it in alongside the readiness/HRV read.

If load is rising while readiness/HRV/sleep are declining, say so plainly and suggest an easier day or two rather than only reporting the load/distance numbers as if they were the whole picture — the whole point of pulling this data is to catch the problem before it shows up in pace or an injury.

**Fitness trend (VO2 max)**: Call `vo2max_trend` (default 90 days, since VO2 max moves slowly) to check whether fitness is actually trending upward through the training block, as a complement to `training_baseline`'s current-value snapshot. If the account/device doesn't report this (all `null`), skip it rather than treating the gap as a red flag.

## Upcoming plan vs. what's actually happening

If the user has an active Garmin Connect training plan, `planned_vs_actual` (default 14 days) returns planned workouts (name, type, planned duration/distance/pace/HR where available) alongside whatever was actually logged that day. Use this to:
- Check adherence — did the user do the planned workout, skip it, or do something different, for the days already in the past within the window.
- Preview what's coming up — the tool also returns future planned dates, useful for "what's on my plan this week" type questions.

This is the most speculative tool in the server — Garmin's plan field mappings aren't fully verified, and in practice many of the planned-side fields (distance, pace, HR targets) may come back `null` even when a plan is active, with only duration reliably populated. Treat it as a helpful cross-check, not a source of precise targets: if `planned_distance_meters`/pace/HR fields are null, just compare on workout name/type/duration and don't fabricate specifics the data doesn't actually contain. Returns `[]` if there's no active plan — treat that as normal, not an error, and fall back to the rest of Step 1's analysis.

## Quick lookups: "What's my target pace/HR?"

For short, direct questions like "what's my target pace for my next run", "what HR should I hold for a threshold run", or "what are my easy/recovery/long-run/threshold targets" — don't run the full Step 1 broad pull. Answer directly and concisely:

1. Call `training_baseline` first. If it returns real data (lactate threshold HR/pace, race predictions), derive the zone targets from it.
2. If `training_baseline` returns `{"status": "unavailable"}` (as it does for some accounts/devices), fall back to:
   - The pace/HR targets already established with the user in this conversation or in Claude's memory (e.g. a calibrated pace/HR table from prior analysis).
   - If no such targets exist yet, pull `activity_hr_zones` on one or two representative recent runs (an easy run and a threshold run from `recent_activities`) to read off real zone boundaries, and pair those with the user's known race-pace target to build the table. For the threshold/interval reference point specifically, don't use the session's whole-activity average pace — pull `activity_laps` and use the actual work-rep segments (see the lap-segment guidance under Step 2), since the average blends in slow recovery jogs and understates true threshold pace.

Answer with a compact table covering the run types that apply — typically **Recovery, Easy/Base, Long Run, Threshold, 10K, 5K, Race pace** — each with a pace range and HR range. Keep the answer short: this is a lookup, not a full training-status report. Only expand into Step 1/Step 3 analysis if the user follows up asking how they're actually performing against these targets.

For 5K and 10K specifically:
- First, check if an actual 5K/10K PB or recent race result is known from the conversation or Claude's memory. If so, use that as the baseline — real results beat any estimate.
- When the user wants a **target** rather than just their historical best, don't simply repeat the PB back to them — that's not a goal, it's the past. Ground a realistic improvement estimate in something measured: pull `vo2max_trend` and compare the VO2 max value on (or nearest to) the PB's date against the current value. Pace scales roughly 1:1 with % VO2 max change for small changes, so apply that same percentage to the PB pace as a physiologically-grounded stretch target (e.g. VO2 max up ~1% since the PB → roughly ~1% faster pace is a realistic near-term goal). If the user is asking about a target further out in the training block (weeks away, allowing more fitness gain), a slightly wider range grounded in continued-but-modest VO2 max gains is reasonable — but don't extrapolate aggressively; VO2 max improvements taper off, especially later in a training block, and a few-percent total improvement over a full block is itself a solid outcome for an experienced runner.
- If `training_baseline` returned real race-time predictions and no PB/VO2max-grounded estimate is possible, use those as a fallback.
- Only as a last resort, with nothing else available (no PB, no VO2 max data, no baseline predictions), estimate from the established threshold work-rep pace using the general rule of thumb that 5K pace is ~20-25 sec/km faster than threshold pace and 10K ~10-15 sec/km faster. Treat this as a weak fallback, not a confident estimate: it assumes a runner with well-developed top-end speed/anaerobic capacity relative to their aerobic threshold, which doesn't hold for a runner whose training is dominated by aerobic volume (Base, Long Run, Threshold) with little dedicated speed/VO2max work — for that kind of runner, actual 5K/10K pace can end up much closer to threshold pace than the ratio suggests, since raw speed rather than aerobic fitness is the limiter. Always caveat clearly when using this fallback that it's a rough estimate that may not hold, and prompt the user to confirm against a real time trial or race result if they have one, rather than presenting it as reliable.
- HR for both is generally high — 10K in upper Zone 4, 5K approaching Zone 5 — since both are shorter/harder efforts than threshold work.

## Comparing race-distance performance over time (10K, half marathon, marathon)

When the user asks how a recent race or effort compares to previous ones at the same distance ("how does this half compare to my last one", "am I getting faster at 10K", "is my marathon fitness actually improving") — use `search_activities` to find comparable prior efforts directly, instead of scanning `recent_activities` by eye or relying on memory of past numbers.

- **Distance isn't exact** — GPS/course variance means a "10K" activity is rarely stored as exactly 10000m. Use a tolerance band on `min_distance_meters`/`max_distance_meters` rather than an exact match:
  - 10K: `min_distance_meters=9800, max_distance_meters=10500`
  - Half marathon: `min_distance_meters=20800, max_distance_meters=21500`
  - Marathon: `min_distance_meters=41800, max_distance_meters=42500`
- Add `activity_type="running"` to exclude cross-training that happens to land in the same distance band, and don't set `start_date` (or set it far back) so the search covers full history, not just a recent window. Raise `limit` above the default 20 for a runner with a long history of races at that distance.
- Results come back newest-first. Treat the most recent match as the run in question (or use the specific `activity_id` if the user already named it from `recent_activities`), and the rest as the historical comparison set, oldest to newest.
- **Not every distance-band match is actually a race** — a training run can land in the same band by coincidence. Use `activity_name` and `training_effect_label` to distinguish, and if it's genuinely ambiguous which entries were real races, ask the user rather than assuming.

For the comparison itself:
- Line up `average_pace_sec_per_km` (and `duration_seconds`) across the matched runs oldest to newest to show the actual trend — several data points, not just the two most recent.
- Compare `average_hr` alongside pace: pace improving at a **lower or similar** HR is genuine fitness improvement; pace improving only because HR rose to match is a harder effort on the day, not more fitness.
- For the run(s) worth a closer look (the most recent, and/or a standout result), pull `activity_laps` to compare pacing strategy (even split vs. positive/negative split) rather than only the whole-activity average. Unlike the structured-session lap segmentation under Step 2, a race is one continuous effort, so the full set of km splits is itself the meaningful unit — not work-rep vs. recovery segmentation.
- Cross-reference `training_baseline`'s race predictions and/or `vo2max_trend` where available — a result meaningfully faster or slower than Garmin's own prediction for that distance is itself worth calling out.

Report progression plainly, grounded in the actual numbers, e.g.: "Your last three half marathons: 1:42:30 (March), 1:39:15 (June), 1:36:48 (this one) — a real ~3-minute-per-race trend, and average HR was actually 4bpm lower this time than March, so this isn't just a harder effort, it's genuine fitness gain."

## Step 2: Drill into a specific activity only when relevant

Only call these when the user asks about (or the analysis specifically requires) one particular run:

- `activity_laps` — per-lap splits, useful for pacing consistency, negative/positive splits, checking against target race pace per km.
- `activity_hr_zones` — time spent in each HR zone for one run, useful for confirming whether an "easy" run was actually easy, or whether a workout hit the intended zones.
- `activity_samples` — fine-grained time series (pace/HR/cadence/elevation), useful for detecting cardiac drift on long runs or precise split analysis beyond what 1km laps show.

Don't call these for every single recent activity by default — that's expensive and usually unnecessary. Reach for them when the user is asking about one specific run, or when something in the broad-picture data (a workout, an outlier pace/HR trend, a data gap) warrants a closer look.

### Critical: structured/interval sessions need lap-level analysis, not the whole-session average

For any session that's a structured workout with reps — activity names like "Threshold", "Tempo", "VO2 Max", "Sprint", "Interval", or a `training_effect_label` of `TEMPO` or `LACTATE_THRESHOLD` — never use the whole-activity `average_pace_sec_per_km` or `average_hr` (from `recent_activities` or `pace_cadence_hr_trend`) as "the pace" or "the effort" for that session. These fields blend fast work reps with slow recovery jogs and warm-up/cooldown, and will substantially understate true effort pace and overstate/understate HR. This was a real mistake made previously (a whole-session average of 5:39/km was reported as "threshold pace" when the actual work reps were 4:48-5:12/km).

Instead, always call `activity_laps` for these sessions and split laps into segments by pattern:
- **Warm-up**: first lap(s), slower pace than the work reps.
- **Work reps**: laps meaningfully faster than the surrounding recovery/warm-up/cooldown laps (often noticeably quicker, e.g. 4:45-5:15/km range for this user's threshold work), typically with HR climbing into Zone 3+.
- **Recovery jogs between reps**: laps that are much slower (often 7-14+ min/km) with HR dropping back down — these sit between work reps and are not part of the effort pace.
- **Cooldown**: final lap(s), slower again.
- **Short continuation laps**: a lap well under the expected distance (e.g. under ~500m when other laps are ~1000m) that immediately follows a work lap at a similar fast pace is very likely the tail end of the same rep (Garmin auto-lap splitting mid-interval), not a separate segment — group it with the work rep it continues, not with recovery.

Report the actual work-rep pace/HR (e.g. as a range across the reps) as the meaningful number, and mention the recovery jog pace/HR separately if relevant, rather than presenting a single blended average as if it represented the workout's effort.

## Charting run data (pace / HR over time)

When visualizing how pace and/or heart rate varied over the course of a run, follow these conventions so charts come out at full fidelity and read the way Garmin's own charts do. These were tuned against real user feedback comparing output to the Garmin Connect app.

### Data source and density
- Pull the time series from `activity_samples` with a **high `max_points` (≈200)**, not the default. Low point counts (e.g. ~70) produce a coarse chart that smooths over real pace noise and looks visibly less complete than Garmin's. ~200 points matches Garmin's density well.
- Build the x-axis from each sample's `elapsed_seconds` converted to **minutes** (elapsed time), never from distance or km-index.

### Always extend the time axis to the true end of the run
- `activity_samples`' even sampling often stops ~15-40 s short of the real finish. Get the true activity duration (from `recent_activities` `duration` / the activity's total time) and make sure the chart's time axis runs all the way to it.
- **Render the x-axis as a true numeric scale**: set `x_axis.min = 0` and `x_axis.max = <total duration in minutes>` (e.g. 118.2 for a 1:58:12 run), with `format: "%.0f"`. Do **not** pass a per-point `x_axis.data` label array for these charts — the renderer thins point-labels and drops the final ticks, so the axis *reads* as ending early (e.g. last tick 104.7 for a 118-min run) even though the line reaches the edge. A numeric min/max axis labels the whole run correctly.
- If the last real sample falls short of the finish, append one final point at the true finish time carrying the closing pace/HR, and say so plainly (it's closing the last ~30 s with measured values, not inventing data).

### Pace formatting
- **Pace is always in min/km, never sec/km.** Provide values as decimal minutes (335 sec/km → 5.58). In prose, refer to paces in mm:ss form (5:35/km), not decimal.
- **Flip the pace y-axis so faster is at the top**, matching Garmin: set `y_axis.min` to the *slower* bound and `y_axis.max` to the *faster* bound (e.g. `min: 6.4, max: 4.6`), with `format: "%.2f"` and a title like "min/km (higher = faster)".
- **Clip GPS dropouts** so they don't blow the scale: cap displayed pace at a sane ceiling (e.g. 7.0 min/km) rather than letting a stopped/lost-signal sample (e.g. 800 sec/km) flatten the whole chart. Note the clipped spike is a GPS artifact.

### Heart rate
- Plot HR in **true bpm** on its own chart with a tight y-range (e.g. 115-165), not scaled or squashed.

### Two aligned charts, not one overlay
- The chart tool has a **single y-axis**, so pace (~5.5) and HR (~145) cannot share one axis honestly — scaling HR into the pace band pushes one line off the chart (a real failure that happened). **Render two separate charts stacked on the same 0→duration minute axis** — one pace (min/km, flipped), one HR (bpm) — so both stay in real units and fully visible. Don't attempt a scaled single-axis overlay.

### Interpretation
- After the charts, read them together: pace evenness vs drift, the HR staircase, and any finishing kick (pace rising while HR peaks near the end = negative-split signature). Keep it grounded in the actual shapes, per Step 3.

### Known tool limitations to state honestly when relevant
- No second (right-side) y-axis, so pace+HR can't be a single dual-axis chart — hence the two-chart approach.
- No target-pace reference line overlay (Garmin's white line) and no area-fill under the curve — these are lines, not Garmin's filled shapes.

## Step 3: Compare against the plan and give feedback

Compare the retrieved data against the user's known race plan and targets — target pace, target finish time, target HR zones, key upcoming workouts or benchmark races — as established in the conversation or Claude's memory of past discussions. If the plan or targets aren't known, ask rather than assuming generic marathon paces.

Structure feedback around:
- **Status**: Is the user on track for their target, ahead, or falling behind? Be specific and reference the actual numbers retrieved, not generic advice.
- **What's going well**: Concrete positives from the data (e.g. consistent cadence, HR trending down at same pace, laps holding steady).
- **What to watch**: Concrete concerns (e.g. rising HR at same pace suggesting fatigue, missed long runs, cadence drift late in runs).
- **Next steps**: Actionable, tied to the plan (e.g. upcoming workout to prioritize, recovery needed, adjustment to target pace given current fitness).

Avoid vague encouragement disconnected from the data — the value of this skill is that the feedback is grounded in what actually happened, not generic training platitudes.
