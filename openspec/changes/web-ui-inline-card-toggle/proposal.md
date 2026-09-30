## Why

The current expandable workout card renders a separate text line for "Coaching rationale & notes" with a toggle arrow below the metric chips, consuming extra vertical space on mobile screens. Moving the toggle icon directly into the metrics line next to the heart rate chip saves a line per card while keeping the card compact and easy to scan.

## What Changes

- Remove the standalone "Coaching rationale & notes" text line from upcoming workout cards.
- Render the expand toggle chevron (`▾`) directly in the metrics line next to the heart rate chip when coaching details exist.
- Update CSS to style the inline toggle icon and handle smooth rotation on expand/collapse.
- Update unit tests in `test_mfa_web_server.py`.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None (spec requirements already specify inline disclosure without prescribing specific line counts).

## Impact

- Web UI: `stridesync/app/mfa_web/server.py`
- Tests: `stridesync/tests/test_mfa_web_server.py`
