## 1. Implementation

- [x] 1.1 Implement `_future_planned_workouts` in `stridesync/app/mfa_web/server.py` querying merged workouts from `planned_workouts` and `plan_overrides` for `workout_date >= CURRENT_DATE`, verified by unit tests in `stridesync/tests/test_mfa_web_server.py`.
- [x] 1.2 Implement `_future_plan_html` helper and CSS styles in `stridesync/app/mfa_web/server.py` formatting badges, targets, pace, HR, and rationales, verified by HTML string assertions.
- [x] 1.3 Integrate `_future_plan_html` at the top of the `/running` endpoint handler in `stridesync/app/mfa_web/server.py` so upcoming plans appear above heart rate zones and weekly volume, verified by integration tests.
- [x] 1.4 Bump pre-release version in `stridesync-dev/config.yaml` to `0.9.2b2` and add changelog entry under `[Unreleased]` in `CHANGELOG.md` and `stridesync/CHANGELOG.md`.
- [x] 1.5 Run full pytest suite and validate specs with `openspec validate --specs --strict`.
