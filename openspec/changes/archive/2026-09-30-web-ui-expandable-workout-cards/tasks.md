## 1. Web UI Layout & Styling

- [x] 1.1 Add `.plan-card`, `.plan-summary`, `.plan-metrics`, `.plan-chip`, and `.plan-details` CSS classes in `stridesync/app/mfa_web/server.py` and verify syntax with `python3 -m py_compile stridesync/app/mfa_web/server.py`.
- [x] 1.2 Refactor `_future_plan_html` in `stridesync/app/mfa_web/server.py` to generate expandable cards with `<details><summary>` and verify output markup renders correctly in local unit tests.

## 2. Testing & Verification

- [x] 2.1 Update `stridesync/tests/test_mfa_web_server.py` to assert expandable card markup, metric chips, and toggle details, and verify with `pytest stridesync/tests/test_mfa_web_server.py`.
- [x] 2.2 Bump pre-release version in `stridesync-dev/config.yaml` to `0.9.3b2` and verify version ordering passes with `pytest stridesync/tests/test_addon_config.py`.
