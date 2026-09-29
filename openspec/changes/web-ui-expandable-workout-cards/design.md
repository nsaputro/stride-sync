## Context

See proposal.md. The UI container has a max width of 26rem (416px).

## Goals / Non-Goals

**Goals:**
- Present upcoming training workouts cleanly within 26rem without horizontal scrolling.
- Provide collapsible progressive disclosure for coaching rationales and execution notes.
- Maintain visual harmony with existing `.row-card` and `.stat-tile` elements.

**Non-Goals:**
- Changing database queries, MCP tools, or sync pipelines.
- Introducing external CSS/JS libraries or frontend frameworks.

## Decisions

- **Native `<details><summary>` for coaching disclosure**:
  - *Rationale*: Zero JavaScript required, fully accessible, and works consistently inside Home Assistant Ingress webviews.
  - *Alternative considered*: Custom JS accordion or modal overlay (unnecessary complexity and Ingress iframe friction).
- **Expandable Workout Cards (`.plan-card`) in `.row-list`**:
  - *Rationale*: Replaces rigid multi-column table layout with vertically structured cards that naturally fit 360–416px mobile viewports.
  - *Alternative considered*: Responsive table with horizontal scroll or `display: block` hack (clunky UX on narrow screens).
- **Compact Metric Chips**:
  - *Rationale*: Groups target distance/duration and target pace/HR into clear, scannable badges.

## Risks / Trade-offs

- [Older browser compatibility with `<details>` styling] → Standard WebKit/Blink/Gecko support is universal; styled cleanly using standard pseudo-elements (`::-webkit-details-marker`).
