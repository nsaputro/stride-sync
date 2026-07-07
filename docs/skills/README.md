# Example Claude Skills for StrideSync

This directory holds example [Claude Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills)
that pair with the StrideSync MCP server — optional, not required to use StrideSync at all. A
Skill is just a `SKILL.md` file with instructions Claude loads on demand; these examples show one
way to turn StrideSync's raw MCP tools (`recent_activities`, `training_baseline`,
`pace_cadence_hr_trend`, etc.) into a specific, opinionated workflow instead of ad-hoc tool calls
every time you ask about a run.

## Available skills

- **[`running-coach/`](running-coach/SKILL.md)** — a running coach that pulls your
  actual Garmin data (via StrideSync) and compares it against your race plan and targets: sync
  health, training baseline, recent activities, pace/cadence/HR trends, training load, and
  recovery/readiness signals (sleep, HRV, training readiness). Handles training-progression
  questions (weekly mileage, long-run build, recovery trend), target-pace/HR lookups, per-activity
  lap/zone drill-downs, and structured-workout (threshold/interval) analysis that correctly
  separates work-rep pace from recovery-jog pace instead of using a misleading whole-session
  average.

## Installing a skill

Copy the skill's folder (e.g. `running-coach/`) into wherever your Claude client loads Skills
from — this varies by client:

- **Claude Code / Claude Code on the web**: copy into `~/.claude/skills/` (personal) or a
  project's `.claude/skills/` directory.
- **Claude.ai / Claude Desktop**: upload via Settings → Capabilities → Skills (check
  [Anthropic's Skills docs](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) for the
  current steps, since this UI changes over time).

The skill itself only calls StrideSync's MCP tools — it doesn't need any StrideSync-specific
setup beyond having the MCP server connected (see `DOCS.md`'s "Connecting Claude to StrideSync"
section).

## Writing your own

These are examples, not the only way to use StrideSync — feel free to copy `running-coach/` as a
starting point and adjust it for your own training plan, race distance, or coaching style, or
write a Skill from scratch around whichever StrideSync tools matter most to you.
