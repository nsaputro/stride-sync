# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Plan

**Always read `PROJECT_PLAN.md` before implementing any new feature.**

- Check which milestone the feature belongs to and confirm it is listed there.
- When you open a PR for a feature, tick its checkbox in `PROJECT_PLAN.md` and include the updated file in the same commit.
- If a feature is not yet in the plan, add it to the appropriate milestone before starting work.

## Purpose

StrideSync is a Home Assistant add-on that syncs running data (activities, cadence, pace, heart
rate, training load) from Garmin Connect and exposes it to Claude over MCP for conversational
analysis. It runs continuously on the HA server — there is no local-only mode and no client-side
install step. Claude Desktop (or any MCP client) connects to it remotely over HTTP.

Two long-running services live inside the add-on:

1. **Sync scheduler** — polls Garmin Connect on a configurable interval (default every 6h) and
   writes normalized activity data into a local SQLite database in the add-on's persistent
   `/data` volume.
2. **MCP server** — serves that data to MCP clients over **Streamable HTTP** (not stdio, since
   the client is not on the same machine as the add-on).

See `PROJECT_PLAN.md` for the detailed architecture, MCP connection instructions, and milestones.

## Git Policy

**Never push directly to `main`.** All changes must go through a pull request:

1. **Always** create the branch from the latest `main`: `git checkout origin/main -b feature/your-description`
2. Commit changes and push the branch
3. Open a PR targeting `main` via the GitHub MCP tools (`mcp__github__create_pull_request`)
4. **Always verify** the PR was created by calling `mcp__github__pull_request_read` immediately after. Only report the PR link once the MCP tool confirms it exists and is open.
5. **Before adding commits** to an existing PR branch, check if the PR is still open with `mcp__github__pull_request_read`. If it was already merged, create a new branch from `origin/main`, cherry-pick the pending commits, push, and open a new PR.

## Home Assistant Add-on Repository Conventions

This repo follows the standard [HA add-on repository layout](https://developers.home-assistant.io/docs/add-ons/repository):

```
stride-sync/
├── repository.yaml          # Add-on repository descriptor (required at root for HA to recognize the store)
├── CLAUDE.md
├── PROJECT_PLAN.md
├── README.md
├── CHANGELOG.md             # Repo-level changelog (Keep a Changelog format)
├── LICENSE
└── stridesync/               # The add-on itself — everything HA Supervisor needs to build/run it
    ├── config.yaml           # Add-on manifest: name, version, slug, options, schema, ports
    ├── build.yaml            # Multi-arch build_from mapping (aarch64 / amd64 → base image tags)
    ├── Dockerfile
    ├── DOCS.md                # Shown in the HA UI "Documentation" tab for this add-on
    ├── CHANGELOG.md           # Shown in the HA UI "Changelog" tab; versions must match config.yaml
    ├── icon.png                # 128x128, shown in the add-on store
    ├── logo.png                # 250x100, shown on the add-on's detail page
    ├── rootfs/                # Copied to `/` in the container image — s6-overlay services + init
    │   └── etc/
    │       ├── cont-init.d/    # One-shot init scripts, run once before services start
    │       └── services.d/     # Long-running s6 services (one directory per service)
    │           ├── sync-scheduler/
    │           │   └── run
    │           └── mcp-server/
    │               └── run
    ├── app/                    # Python application code, copied into the image by the Dockerfile
    └── tests/
```

- `config.yaml` is the single source of truth for the add-on's user-facing options (`options:` +
  `schema:` keys) — Garmin credentials, sync interval, MCP port, log level. The Home Assistant
  Supervisor reads this file directly from the repo to decide whether to offer an update, so its
  `version` field must never point at a Docker image that hasn't been published yet (see
  Versioning below).
- `DOCS.md` and `CHANGELOG.md` **must live inside the add-on folder** (`stridesync/`), not just at
  the repo root — Home Assistant renders these two files verbatim in the add-on's UI tabs.
- `icon.png` / `logo.png` are also add-on-folder-local; HA does not read repo-root images.

## Base Image & Init System

Base image: **`ghcr.io/hassio-addons/base`** (Alpine Linux + [s6-overlay](https://github.com/just-containers/s6-overlay) init).
Pin the exact tag per architecture in `build.yaml`; do not float `:latest`.

s6-overlay is what lets a single container run **two independent long-running processes** — the
sync scheduler and the MCP server — as supervised services instead of a single foreground
process. Each service gets its own `rootfs/etc/services.d/<name>/run` script:

- s6 restarts a service automatically if it exits — this matters for the sync scheduler, which
  should never take the MCP server down with it if a Garmin sync fails.
- Each service logs independently (`bashio::log.info` from its own `run` script), so a crash in
  one is easy to distinguish from the other in the HA add-on log viewer.
- One-shot setup (validating that Garmin credentials are present, running DB migrations before
  either service starts) belongs in `rootfs/etc/cont-init.d/`, not inside a service's `run`
  script — cont-init scripts run once, in order, before any `services.d` entry starts.

Every `run` script starts with `#!/usr/bin/with-contenv bashio` so it can read add-on options via
`bashio::config` and log through `bashio::log.*`.

## Coding Conventions

- **Python 3.12**, type hints on all function signatures — this is a long-running service, not a
  script, so type errors should be caught before they reach production.
- Keep the sync scheduler and MCP server as **separate, independently runnable modules**
  (`app/sync/` and `app/mcp/`) even though they share the same SQLite database and codebase. Each
  has its own `s6` service and its own entry point (`python3 -m app.sync.scheduler` /
  `python3 -m app.mcp.server`) so either can be started standalone for local testing without
  pulling in the other.
- Garmin auth/session code lives behind a single client interface (`app/sync/garmin_client.py`)
  so the unofficial-API breakage risk (see `PROJECT_PLAN.md`) is isolated to one module — sync
  and MCP code should never call `garmy` (or its fallback) directly.
- Fail loud, not silent: a failed sync must produce a clear log line and an updated "last sync
  status" the MCP server can surface — never a silently stale database.

## Local Development & Testing

You do not need Home Assistant running to develop or test this add-on. Build and run the
container standalone first; install it into HA only once it behaves correctly on its own.

```bash
# Build the add-on image standalone (same Dockerfile HA Supervisor uses)
docker build -t stridesync-dev ./stridesync

# Run it with a local /data volume and options.json substituting for HA Supervisor's config UI
mkdir -p .dev-data
cat > .dev-data/options.json <<'EOF'
{
  "garmin_username": "you@example.com",
  "garmin_password": "changeme",
  "sync_interval_hours": 6,
  "mcp_port": 8765,
  "log_level": "info"
}
EOF

docker run --rm -it \
  -p 8765:8765 \
  -p 8767:8767 \
  -v "$(pwd)/.dev-data:/data" \
  stridesync-dev
```

- `bashio::config` reads `/data/options.json` — outside of HA Supervisor, you provide this file
  yourself, as shown above.
- Once running, point an MCP client at `http://localhost:8765/mcp` to exercise the MCP server
  without needing HA ingress or `mcp-proxy` on the HA side.
- For an MFA/2FA account, `http://localhost:8767/` serves the one-time login UI directly (this
  is what a real HA install reaches through the add-on's ingress panel instead).
- Only after standalone behavior is verified should you add the repo to a real HA instance
  (**Settings → Add-ons → Add-on Store → ⋮ → Repositories** → this repo's URL) to test Supervisor
  packaging, ingress, and the options UI.

## Versioning

Follow the same three-file convention used in `siap-jalan` and `health-recorder`:

| File | Who sets it | Rule |
|------|-------------|------|
| `stridesync/NEXT_VERSION` | PRs | Next version to release (plain `X.Y.Z`). |
| `stridesync/config.yaml` `version` | Release workflow only | Always the last *released* version — never edit in feature PRs. |
| `stridesync-dev/config.yaml` `version` | PRs | Tracks `{NEXT_VERSION}b{N}` (pre-release suffix). |

Use semantic versioning: `PATCH` for fixes, `MINOR` for new user-facing features, `MAJOR` for
breaking changes (e.g. a Garmin auth library swap that requires re-authentication).

### Pre-release version must always track NEXT_VERSION

`stridesync-dev/config.yaml` must always be `{NEXT_VERSION}b{N}`:

1. Read `stridesync/NEXT_VERSION` (e.g. `0.1.1`).
2. List existing pre-release tags: `mcp__github__list_tags owner=nsaputro repo=stride-sync`.
   Filter for tags like `v0.1.1b*`. Find the highest `b` number; `N = highest + 1`. If none
   exist, `N = 1`.
3. Set `stridesync-dev/config.yaml` `version` to `{NEXT_VERSION}b{N}` (e.g. `0.1.1b1`).
4. Every PR that adds new code and wants to be testable via the dev channel should bump this
   value — the correct value is always strictly greater than every existing tag.

## Changelog

Every PR that changes add-on behavior must add an entry under `## [Unreleased]` in both
`CHANGELOG.md` (repo root) and `stridesync/CHANGELOG.md` (add-on-local, shown in the HA UI),
using [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) categories (`Added`, `Changed`,
`Fixed`, `Removed`).

## CI / Release

Three pipelines, following the same split used in `siap-jalan` and `health-recorder`. CI never
publishes images — that's exclusively owned by the release and pre-release workflows.

**CI** (`.github/workflows/ci.yml`) — runs on every push to `main`, `dev`, `claude/**`,
`feature/**`, `fix/**` and on PRs targeting `main`:

- yamllint on `stridesync/config.yaml` + `stridesync/build.yaml`
- hadolint on `stridesync/Dockerfile`
- Version-ordering check: `stridesync/NEXT_VERSION` must be greater than `stridesync/config.yaml`
  `version` (catches the release workflow ever being skipped without bumping `NEXT_VERSION`)
- Python `ast.parse` syntax check on `stridesync/app/`
- `pytest` on `stridesync/tests/`
- Docker build smoke test for the add-on (`linux/amd64`, no push)

`ci-pass` is the single required status check for branch protection — it exits 0 immediately for
PRs opened by `github-actions[bot]` (the auto-generated post-release PR, whose real jobs are
skipped rather than run) and otherwise requires every real job to have succeeded.

**Pre-release** (`.github/workflows/prerelease.yml`) — `workflow_dispatch` only. Use this for
beta/dev-channel builds **before** cutting a stable release, so a real bug (e.g. one that only
shows up when the built image actually runs, which CI's build-only smoke test won't catch) is
caught on the dev channel instead of the stable one:

1. Reads `stridesync-dev/config.yaml` `version`; must carry a pre-release suffix (`0.1.1b1`,
   `0.1.1rc1`) — a pure `X.Y.Z` is rejected (use the Release workflow instead).
2. Tags `v{version}` and pushes it.
3. Builds and pushes `{arch}-stridesync:{version}` to GHCR for `amd64` + `aarch64` — **no**
   `:latest` tag, so it never gets pulled by a stable install.
4. Install the dev channel add-on (slug `stridesync_dev`, host port `8766`) on a real HA
   instance to verify it before promoting the same fix to a stable release.

**Release** (`.github/workflows/release.yml`) — `workflow_dispatch` only:

1. Reads `stridesync/NEXT_VERSION`, validates it's a pure `X.Y.Z` semver, tags `vX.Y.Z`.
2. Builds and pushes `{arch}-stridesync:{version}` + `:latest` to GHCR for `amd64` + `aarch64`.
3. Creates a GitHub release with auto-generated notes.
4. Opens a `chore/post-release-X.Y.Z` PR (labelled `post-release`) that stamps
   `stridesync/config.yaml` to the released version, bumps `stridesync/NEXT_VERSION` to the next
   patch, and moves `CHANGELOG.md`'s `[Unreleased]` entries into a dated `[X.Y.Z]` section
   (regenerating `stridesync/CHANGELOG.md` from it). It does **not** touch
   `stridesync-dev/config.yaml` — bump that in a normal PR per the versioning section above.

**To ship a pre-release:**

1. Ensure `stridesync-dev/config.yaml` version is `{NEXT_VERSION}b{N}` (see versioning rules
   above) and merged to `main`.
2. **Actions → Pre-release → Run workflow** (no inputs — version read from
   `stridesync-dev/config.yaml`).

**To ship a stable release:**

1. Ensure `stridesync/NEXT_VERSION` holds the version to release and everything is merged to
   `main` — ideally after the same code has already been validated via a pre-release.
2. **Actions → Release → Run workflow** (no inputs — version comes from `NEXT_VERSION`).
3. Review and merge the auto-created `chore/post-release-X.Y.Z` PR — check
   `stridesync/CHANGELOG.md` in particular, since its bullets are auto-extracted.

### Branch protection

Require exactly one status check on `main`: **`CI Pass`**. Do not add the individual job names
(`Lint`, `Unit tests`, etc.) — they're skipped (not passed) on bot-created PRs, which would block
those PRs from merging if required directly.
