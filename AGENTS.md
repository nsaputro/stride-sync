# AGENTS.md

This file provides guidance to Antigravity and other AI coding agents when working with code in this repository.

## Spec-Driven Development with OpenSpec

This repository uses **[OpenSpec](https://github.com/Fission-AI/OpenSpec)** for specification-driven development. The source of truth for system capabilities and requirements lives in `openspec/specs/`.

### Available OpenSpec Workflows

Workflows are available as slash commands or skills in `.agents/`:

| Command / Workflow | Purpose |
|---|---|
| `/opsx-propose <idea>` | Propose a new change, generating proposal, specs deltas, design, and tasks in one step |
| `/opsx-explore <query>` | Explore the codebase, existing specs, and architecture without modifying files |
| `/opsx-apply <change>` | Apply an approved change by working through its task checklist |
| `/opsx-update <change>` | Update an in-flight change proposal or its tasks |
| `/opsx-sync` | Validate and sync specs against implementation |
| `/opsx-archive <change>` | Archive a completed change and merge its delta requirements into `openspec/specs/` |

### OpenSpec Rules

1. **Check existing specifications first**: Before proposing or modifying capabilities, review `openspec/specs/` with `openspec list --specs`.
2. **Behavioral contracts**: Specs define observable behavior, inputs, outputs, constraints, and testable scenarios (using `#### Scenario:` with `WHEN`/`THEN`). Implementation details belong in `design.md` or `tasks.md`.
3. **Spec validation**: Run `openspec validate --specs --strict` before completing changes.

---

## Project Management (GitHub Projects Kanban Board)

Project tracking and task management is organized on the **[StrideSync GitHub Project Board](https://github.com/users/nsaputro/projects/2)** linked to `nsaputro/stride-sync`.

### Board Columns & Lifecycle Rules

The board uses four status columns: `Backlog`, `Ready`, `In Progress`, and `Done`.

| Column | Purpose | Rules & Transitions |
|---|---|---|
| **`Backlog`** | Unscheduled ideas, prospective features, and deferred validations | Stored as draft project items or issues. No branch or active planning needed. |
| **`Ready`** | Prioritized tasks ready for immediate implementation | **Mandatory**: Any item moving to `Ready` **must be converted into a GitHub Issue** in `nsaputro/stride-sync`. Define clear scope and acceptance criteria in the issue description. |
| **`In Progress`** | Actively being planned or implemented | Move the issue to `In Progress` when starting an OpenSpec change (`/opsx-propose` or `/opsx-apply`) on a `feature/` branch. |
| **`Done`** | Merged and verified tasks | When the PR merges to `main` and the OpenSpec change is archived (`/opsx-archive`), move the issue to `Done`. |

### Agent Workflow with the Project Board

1. **Selecting work**: Pick tasks exclusively from the `Ready` column (or promote an item from `Backlog` by converting it into a GitHub Issue in `Ready` first).
2. **Starting work**: Move the issue from `Ready` to `In Progress`:
   ```bash
   gh project item-edit 2 --owner nsaputro --url "https://github.com/nsaputro/stride-sync/issues/<number>" --field "Status" --value "In Progress"
   ```
3. **Branching & Planning**: Create a feature branch (`git checkout -b feature/<issue-name>`) and initiate OpenSpec planning (`/opsx-propose "<issue-name>"`).
4. **Pull Request**: Reference the issue in the PR description (e.g. `Closes #<number>`).
5. **Completion**: Once merged, move the issue to `Done`:
   ```bash
   gh project item-edit 2 --owner nsaputro --url "https://github.com/nsaputro/stride-sync/issues/<number>" --field "Status" --value "Done"
   ```

---

## Purpose

StrideSync is a Home Assistant add-on that syncs running data (activities, cadence, pace, heart rate, training load, recovery/wellness, gear) from Garmin Connect and exposes it to AI agents over MCP (Streamable HTTP) for conversational analysis. It runs continuously on the HA server — there is no local-only mode and no client-side install step.

Two long-running services live inside the add-on:

1. **Sync scheduler** (`app/sync/`) — polls Garmin Connect on a configurable interval (default every 6h) and writes normalized data into `/data/stridesync.db`.
2. **MCP server** (`app/mcp/`) — serves that data to MCP clients over **Streamable HTTP** (port 8765, dev 8766).

---

## Git Policy

**Never push directly to `main`.** All changes must go through a pull request:

1. **Always** create the branch from latest `main`: `git checkout origin/main -b feature/your-description`
2. Commit changes and push the branch.
3. Open a PR targeting `main`.
4. Branch protection requires the **`CI Pass`** check.

---

## Home Assistant Add-on Repository Conventions

This repo follows the standard Home Assistant add-on repository layout:

```
stride-sync/
├── repository.yaml          # Add-on repository descriptor (required at root)
├── AGENTS.md                # Agent instructions and guidelines
├── CLAUDE.md                # Claude instructions
├── PROJECT_PLAN.md          # Architectural history and milestone log
├── README.md
├── CHANGELOG.md             # Repo-level changelog (Keep a Changelog format)
├── LICENSE
├── openspec/                # OpenSpec specifications and changes
│   ├── config.yaml
│   ├── specs/               # Baseline capability specifications
│   └── changes/             # Active and archived changes
├── .agents/                 # Antigravity workflows and skills
│   ├── skills/              # openspec-* and running-coach skills
│   └── workflows/           # opsx-* slash command workflows
└── stridesync/               # The add-on itself
    ├── config.yaml           # Add-on manifest: options, schema, ports, version
    ├── build.yaml            # Multi-arch build_from mapping (aarch64 / amd64)
    ├── Dockerfile
    ├── DOCS.md                # Rendered in HA UI Documentation tab
    ├── CHANGELOG.md           # Rendered in HA UI Changelog tab (must match config.yaml)
    ├── icon.png               # 128x128 store icon
    ├── logo.png               # 250x100 detail page logo
    ├── NEXT_VERSION           # Next release version (plain X.Y.Z)
    ├── rootfs/                # s6-overlay services and cont-init scripts
    │   └── etc/
    │       ├── cont-init.d/   # One-shot init scripts (migrations, validation)
    │       └── services.d/    # s6 supervised services (sync-scheduler, mcp-server)
    ├── app/                   # Python application code
    └── tests/                 # pytest suite
```

- `config.yaml` is the single source of truth for options and schema. Its `version` field is only updated during release workflows.
- `DOCS.md` and `CHANGELOG.md` must live inside `stridesync/` (not just repo root).

---

## Base Image & Init System

Base image: **`ghcr.io/hassio-addons/base`** (Alpine Linux + s6-overlay).
Pin exact tags per architecture in `build.yaml`; never float `:latest`.

s6-overlay supervises both independent long-running processes:
- `rootfs/etc/services.d/sync-scheduler/run`
- `rootfs/etc/services.d/mcp-server/run`

If `sync-scheduler` fails or restarts, `mcp-server` remains alive and answers queries from cached SQLite data.

---

## Coding Conventions

- **Python 3.12**, strict type hints on all function signatures.
- Keep the sync scheduler and MCP server as **separate, independently runnable modules** (`app/sync/` and `app/mcp/`).
- Garmin auth/session code lives behind a single client interface (`app/sync/garmin_client.py`) to isolate unofficial API breakage risks.
- **Fail loud, not silent**: a failed sync must write an updated status to the `sync_log` table so staleness is visible via MCP and web UI.
- All MCP tools are read-only except gear assignment write-backs (`add_activity_gear`, `remove_activity_gear`), which require explicit user confirmation.

---

## Versioning (Three-File Convention)

| File | Who sets it | Rule |
|------|-------------|------|
| `stridesync/NEXT_VERSION` | PRs | Next version to release (plain `X.Y.Z`). |
| `stridesync/config.yaml` `version` | Release workflow only | Always the last released version — never edit in feature PRs. |
| `stridesync-dev/config.yaml` `version` | Release workflow sets to `{NEXT_VERSION}b1`; PRs bump further. | Tracks `{NEXT_VERSION}b{N}` (pre-release suffix). |

---

## Changelog

Every PR that changes add-on behavior must add an entry under `## [Unreleased]` in both:
1. `CHANGELOG.md` (repo root)
2. `stridesync/CHANGELOG.md` (add-on local, shown in HA UI)

Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) categories: `Added`, `Changed`, `Fixed`, `Removed`.

---

## CI / Release

Pipelines defined in `.github/workflows/`:
- **CI** (`ci.yml`): yamllint, hadolint, version-ordering check, Python `ast.parse` syntax check, `pytest`, Docker smoke build. Required status check: `CI Pass`.
- **Pre-release** (`prerelease.yml`): builds and publishes `{arch}-stridesync:{version}` from `stridesync-dev/config.yaml`.
- **Release** (`release.yml`): tags `v{NEXT_VERSION}`, publishes `:latest` images, creates GitHub Release, and opens post-release bump PR.
