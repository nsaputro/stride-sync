## Why

The current 5-column table on the Running tab overflows horizontally on mobile viewports (<416px) and compresses coaching notes and rationales into 1-2 character vertically wrapped columns. Replacing the table with mobile-optimized expandable workout cards provides an at-a-glance training schedule with on-demand access to coaching rationale.

## What Changes

- Replace the 5-column HTML table in `_future_plan_html` with mobile-optimized expandable workout cards inside `.row-list`.
- Display workout date, weekday, workout name, override badge (`[Override]` or `[Garmin]`), target distance/duration, and target pace/HR directly on the card header.
- Provide a native `<details><summary>` collapsible accordion on each card that smoothly expands coaching rationale (`reason`), specific instructions (`notes`), and superseded workout name (`Original: <del>...</del>`).
- Add responsive card CSS styling with zero horizontal overflow.
- Update web-ui specifications and automated test assertions.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `web-ui`: Updates the Running Analytics Tab presentation requirement from a table to mobile-friendly expandable workout cards with interactive coaching rationale disclosure.

## Impact

- Web UI code: `stridesync/app/mfa_web/server.py` (`_future_plan_html` and `_CSS`).
- Tests: `stridesync/tests/test_mfa_web_server.py`.
- No API, database, or MCP protocol changes.
