## Context

See `proposal.md`. StrideSync web UI renders the Running tab via `app/mfa_web/server.py`.

## Goals / Non-Goals

**Goals:**
- Query upcoming workouts on or after current date, merging `planned_workouts` and `plan_overrides`.
- Render a responsive HTML table at the top of `/running` above Heart Rate Zones and Weekly Distance.

**Non-Goals:**
- In-browser interactive editing or override creation (overrides remain managed via MCP tools).
- Modifying underlying database schema or MCP server endpoints.

## Decisions

- **Date-union query**: Use a CTE with `SELECT workout_date FROM planned_workouts UNION SELECT workout_date FROM plan_overrides` where `workout_date >= :today` ordered chronologically. Ensures overrides without a base Garmin plan are included.
- **Top placement in Running tab**: Prepend `_future_plan_html(settings)` directly in `running(request)` before `_hr_zone_ranges_html(settings)` and `_weekly_distance_html(settings)`.
- **Responsive HTML rendering**: Use `<div class="table-container">` with overflow-x auto, clean badge pills (`.badge-override`, `.badge-garmin`), and formatted pace/HR subtexts.

## Risks / Trade-offs

- [No future workouts in DB] → Render muted empty-state card `<div class="card"><p class="muted">No upcoming workouts scheduled.</p></div>`.
- [Missing DB path or uninitialized DB] → Gracefully return empty list and empty-state card.
