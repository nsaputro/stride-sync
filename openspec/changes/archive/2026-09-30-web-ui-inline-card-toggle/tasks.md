## 1. Web UI Layout & Styling

- [x] 1.1 Update `summary.plan-summary` and add `.plan-toggle-icon` CSS styles in `stridesync/app/mfa_web/server.py` and verify syntax with `python3 -m py_compile stridesync/app/mfa_web/server.py`.
- [x] 1.2 Refactor `_future_plan_html` in `stridesync/app/mfa_web/server.py` to embed the toggle chevron directly inside the metrics row next to the HR chip and verify rendering.

## 2. Testing & Verification

- [x] 2.1 Update `stridesync/tests/test_mfa_web_server.py` to assert the inline toggle icon and absence of standalone rationale label text, and verify with pytest.
- [x] 2.2 Bump pre-release version in `stridesync-dev/config.yaml` to `0.9.3b3` and verify config validation passes.
