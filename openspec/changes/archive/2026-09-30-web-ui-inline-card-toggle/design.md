## Context

See proposal.md. The workout cards currently display a separate line `<summary class="plan-summary">Coaching rationale & notes</summary>`.

## Goals / Non-Goals

**Goals:**
- Eliminate the extra line by placing the expand toggle icon into the metrics row alongside pace and HR chips.
- Retain semantic `<details><summary>` HTML without requiring JavaScript.
- Maintain visual consistency and responsive tap targets.

**Non-Goals:**
- Modifying workout data, database models, or MCP tools.

## Decisions

- **`<summary>` as the metrics flex container**:
  - *Rationale*: By setting `summary.plan-summary` to `display: flex; align-items: center; gap: 0.4rem`, the metric chips and toggle icon sit side-by-side on one row.
  - *Alternative considered*: Floating a button next to the metrics and using JavaScript event listeners (violates zero-JS constraint and Ingress sandboxing).
- **`.plan-toggle-icon` chip next to HR**:
  - *Rationale*: Provides a dedicated, clear visual affordance (`▾` rotating to `▴` when open) styled similarly to `.plan-chip` with hover/active states.

## Risks / Trade-offs

- [Clicking anywhere on the summary row toggles `<details>`] → This improves mobile usability by providing a generous tap target without needing precision tapping.
