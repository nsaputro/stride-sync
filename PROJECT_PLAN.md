# 🏃 StrideSync — Project Plan

**A Home Assistant add-on that syncs Garmin Connect running data and exposes it to Claude via MCP for conversational analysis**

---

## Vision

StrideSync keeps your Garmin Connect running data flowing into a database you own, running
continuously on the same server as the rest of your home automation — no laptop cron job, no
local-only setup, nothing to remember to start. It exposes that data to Claude (or any MCP
client) over the network so you can ask conversational questions about your training — cadence
trends, pace splits, heart-rate zones, training load — without opening a dashboard.

It is **read-only**: StrideSync never writes back to Garmin. It only reads activities and stores
them locally.

---

## 1. Architecture

```
                          ┌─────────────────────────────────────────┐
                          │   HA Add-on container (s6-overlay)        │
                          │                                           │
  Garmin Connect  ◄───────┤  sync-scheduler (s6 service)              │
   (unofficial API)       │    - python-garminconnect                  │
                          │    - runs every N hours (configurable)     │
                          │    - writes to SQLite in /data             │
                          │                                           │
                          │  mcp-server (s6 service)                   │
                          │    - garmy-mcp wrapped with mcp-proxy       │
  Claude Desktop  ◄───────┤    - Streamable HTTP transport, port 8765  │
   (MCP client, remote)   │    - reads from the same SQLite DB          │
                          └─────────────────────────────────────────┘
```

### Garmin Connect sync

- **Library**: [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect) for
  Garmin Connect authentication and activity sync.
- **Originally `garmy`, migrated after Garmin's March 2026 Cloudflare rollout.** Three
  successive fixes on top of `garmy` (a corrected User-Agent, `curl_cffi` TLS-fingerprint
  impersonation, then a human-like login delay) all failed to get past Garmin's Cloudflare bot
  challenge on SSO login — see "Known risk: unofficial Garmin auth breakage" below for the full
  investigation. `python-garminconnect` already implements a 5-strategy cascading login chain
  (mobile app API / web widget / full portal, each tried with both `curl_cffi` impersonation and
  plain `requests`) plus its own anti-bot timing delays, and is actively maintained against
  Garmin's changes — so it replaced `garmy` entirely rather than layering a fourth fix on top.
  The library sits behind the single `app/sync/garmin_client.py` interface (see `CLAUDE.md`) so a
  future swap, if ever needed again, stays a one-file change, not a rewrite.
- Auth credentials (`garmin_username` / `garmin_password`) come from add-on options, never
  hardcoded or logged.

### Scheduled sync service

- Runs as its own **s6 service** (`rootfs/etc/services.d/sync-scheduler/run`), independent of the
  MCP server process.
- Interval is **configurable via `config.yaml`**, **default every 6 hours**.
- Writes normalized activity data (pace, cadence, HR series, distance, duration, training load
  metrics reported by Garmin) to a **local SQLite database** stored in the add-on's persistent
  `/data` volume (`/data/stridesync.db`), so it survives add-on restarts and updates.
- Each sync run records its own outcome (success / partial / failed, record count, error message)
  in a `sync_log` table — the MCP server can surface "last successful sync" and "last sync error"
  directly in conversation, rather than a user discovering stale data on their own.

### MCP server

- Built with [`fastmcp`](https://gofastmcp.com) directly (`app/mcp/server.py`), exposing five
  purpose-built tools (`recent_activities`, `activity_laps`, `pace_cadence_hr_trend`,
  `training_load_summary`, `last_sync_status`) on top of `app/db/schema.sql`, rather than
  [`garmy-mcp`](https://pypi.org/project/garmy-mcp/)'s bundled server — `garmy-mcp`'s
  schema-specific tool (`get_health_summary`) queries a `daily_health_metrics` table that doesn't
  exist in our schema, and this milestone wants purpose-built tools, not a generic
  run-arbitrary-SQL tool. This is the "equivalent MCP tool/resource layer built directly on the
  SQLite schema" fallback this section originally anticipated.
- Exposes **Streamable HTTP transport**, not stdio — this add-on runs on the Home Assistant
  server, not on the same machine as the Claude client, so an stdio-piped subprocess isn't an
  option. Modern `fastmcp` (the same library `garmy-mcp` itself depends on) serves Streamable
  HTTP **natively** via `mcp.run(transport="http", ...)` — no separate `mcp-proxy` process runs
  *inside* the add-on. (`mcp-proxy` is still used **client-side**, e.g. by Claude Desktop, to
  bridge its local stdio-only integration to this remote HTTP endpoint — see §2. That is a
  different process, on a different machine, doing a different job.)
- Runs as its own **s6 service** (`rootfs/etc/services.d/mcp-server/run`) on a **configurable
  port** (default `8765`), reading the sync scheduler's SQLite DB over a **read-only** connection
  (`sqlite3.connect("file:...?mode=ro", uri=True)`) — the MCP server must never be able to write
  to the sync scheduler's database.
- **Read-only**: exposes tools/resources for querying activities, trends, and summaries. No
  write-back to Garmin is planned initially (see Milestones — a future write-back milestone would
  need explicit user confirmation flows and is out of scope for v1.0).

### HA add-on configuration (`config.yaml` `options:` / `schema:`)

| Option | Purpose | Default |
|---|---|---|
| `garmin_username` | Garmin Connect account email | — (required) |
| `garmin_password` | Garmin Connect account password | — (required, `password` schema type) |
| `sync_interval_hours` | How often the sync scheduler polls Garmin Connect | `6` |
| `mcp_port` | Port the MCP server listens on (Streamable HTTP) | `8765` |
| `log_level` | Log verbosity for both services | `info` |

All of the above are exposed in the HA Supervisor's add-on Configuration UI automatically once
declared in `config.yaml` — no separate UI code needed.

### Known risk: unofficial Garmin auth breakage

Garmin does not offer a public API for personal Connect data — every sync library in this space
(`garmy`, `python-garminconnect`, etc.) depends on reverse-engineered SSO/login flows that Garmin
can and does change without notice. **This already happened once**: in March 2026, Garmin put
Cloudflare in front of their SSO login, breaking unauthenticated scripted logins across the
ecosystem until the libraries adapted.

Design implications:

- **Fail loud, never silent.** A broken auth flow must produce a clear, actionable log line
  (`bashio::log.error`) and an entry in `sync_log` with `status = "failed"` and the underlying
  exception message — not a sync that silently no-ops and leaves the database looking current.
- **Surface staleness through the MCP server itself.** Any MCP tool that returns activity data
  should be able to report "last successful sync: N days ago" so a conversation with Claude
  surfaces the problem instead of Claude reasoning over stale data as if it were current.
- **No auto-retry storms.** If auth is broken, retrying every sync interval against a broken SSO
  flow risks the account being flagged for suspicious activity. Back off and log distinctly from
  "transient network failure" vs. "auth flow structurally broken, needs a library update." Applied
  concretely to the MFA case below: once a fresh login reveals an account needs MFA,
  `GarminClient` persists a marker (`.mfa_required` next to the token files) and fails fast on
  every later call while it's still set, instead of repeating a fresh SSO login attempt every
  `sync_interval_hours` forever — that attempt can't succeed without the one-time bootstrap
  anyway. Cleared automatically the next time a session is found valid.
- **Isolate the blast radius.** Because sync and MCP are separate s6 services, a broken Garmin
  auth flow degrades the sync scheduler only — the MCP server keeps serving whatever was last
  successfully synced, with clear staleness info, rather than the whole add-on going down.

**MFA/2FA accounts are supported via a one-time interactive login, not automatically.**
`garmy`'s SSO login doesn't raise an exception when an account requires MFA and no interactive
prompt callback is supplied (which StrideSync, running headless, never supplies) — it silently
returns a `("needs_mfa", state)` tuple instead. This surfaced for real (a user with MFA enabled
hit exactly this, and their account can't have MFA disabled). Two changes fixed it properly
rather than just reporting it more clearly:

1. `GarminClient.login()` no longer calls a fresh SSO login on every sync — a fresh login always
   re-runs the full flow, which would re-trigger MFA every single sync forever. It now checks
   for a cached session first (`AuthClient.is_authenticated`), then a refreshable one
   (`needs_refresh` → `refresh_tokens()`, which uses the long-lived OAuth1 token and does **not**
   need MFA), and only falls back to a fresh SSO login if neither exists.
2. `app/sync/bootstrap_login.py` — a one-time interactive CLI (`python3 -m
   app.sync.bootstrap_login`, run via `docker exec` or HA's Terminal & SSH add-on) that performs
   that first fresh login, prompts for the MFA code, and persists the resulting session to
   `garmin_token_dir` (`/data/.garmin_tokens`) — the same location `login()` checks first. Every
   scheduled sync afterward reuses/refreshes that session.

A **web-based MFA entry flow** through HA ingress — flagged by the same user who hit this, since
terminal access isn't something every HA user has set up — is now implemented too:
`app/mfa_web/server.py`, a small Starlette app reached at the add-on's ingress panel
(`ingress: true`/`ingress_port` in `config.yaml`, revisiting the v0.4 milestone's original "no
ingress" decision). It shares `app/sync/mfa_login.py`'s login/resume logic with the CLI bootstrap
above, so both entry points implement the flow exactly once. Login state (the pending
`("needs_mfa", state)` tuple) lives in a single in-process slot — correct because there is
exactly one Garmin account per add-on install — rather than a per-visitor session store.

**Confirmed against `garmy` via live testing — Garmin's Cloudflare bot management, not an
application-level rejection.** A real account hit `401 Client Error: Unauthorized` on the plain
SSO signin GET (`https://sso.garmin.com/sso/signin?id=gauth-widget...`) — *before* credentials
were even submitted. Copying the identical URL into a real mobile browser, on the same
account/network, succeeded instantly and completed the full login (including MFA). Two fixes,
in sequence, both needed:

1. `garmy`'s Android User-Agent (`garmy.core.config.UserAgents.ANDROID_APP`) is the literal
   Android package name `"com.garmin.android.apps.connectmobile"`, not a real User-Agent string
   (unlike garmy's own correctly-formatted iOS constant, `"GCM-iOS-5.12.24"`) — and identical
   across every garmy install, an easy fingerprint to single out. `garmy` doesn't expose a
   supported way to override this (its public `set_config()` only reaches one of the two places
   this UA is read from — see `app/sync/garmy_ua_override.py`'s module docstring), so
   `garmy_ua_override.apply()` patches both. **This alone did not resolve it** — confirmed by
   live retesting on a rebuilt image.
2. Retesting with enhanced error diagnostics (`describe_transport_error()` in
   `garmin_client.py`, appending response headers/body to transport-error messages) confirmed
   the real cause: `server=cloudflare`, a `cf-ray` header, and an HTML body with `class="no-js"`
   — a genuine Cloudflare bot-challenge page, which no amount of header tweaking can defeat since
   Cloudflare's bot management checks the TLS/JA3 handshake fingerprint itself, before any HTTP
   request is even sent. This is the same event already known ecosystem-wide: Garmin put
   Cloudflare in front of SSO in March 2026, which deprecated `garth` entirely (its maintainer
   couldn't work around it) and forced `python-garminconnect` to adopt `curl_cffi` (a
   `requests`-compatible client that can impersonate a real browser's TLS fingerprint) to stay
   working. `app/sync/garmy_tls_impersonation.py` applies the same fix to `garmy`'s SSO login
   flow specifically (not `APIClient`'s ordinary data-fetch requests, which aren't gated behind
   this rule) — see that module's docstring for the two `garmy`-internals compatibility gaps it
   has to patch around (`GarminOAuth1Session`'s `parent.adapters` access, and
   `curl_cffi`'s exception types not being `requests` exception subclasses).

3. **TLS impersonation alone still didn't clear it** — confirmed by live retesting (the error
   message's format changed from `requests`'s to `curl_cffi`'s, proving the new transport was
   actually used, but the same Cloudflare challenge came back). Investigated
   `python-garminconnect`'s actual current implementation directly: it does the same `curl_cffi`
   TLS impersonation *and* inserts a randomized delay (3-8 seconds for the same widget-flow login
   `garmy` uses) between fetching the login page and submitting credentials — treating request
   *timing* as a separate Cloudflare signal from the TLS handshake itself. New
   `app/sync/garmy_login_delay.py` reproduces this by patching `garmy.auth.sso`'s
   `_perform_initial_login` (the credential-submitting POST) to sleep first, matching the
   GET-then-wait-then-POST pattern rather than firing both back-to-back.

None of these three fix attempts on top of `garmy`, live-retested in sequence (UA, TLS
fingerprint, timing), cleared the block — the same Cloudflare challenge came back every time.
That is the point at which this project **migrated the underlying library from `garmy` to
`python-garminconnect`** rather than attempting a fourth `garmy`-specific patch: the
`garmy_ua_override.py` / `garmy_tls_impersonation.py` / `garmy_login_delay.py` modules (and their
tests) were removed, `requirements.txt` now depends on `garminconnect` directly, and
`app/sync/garmin_client.py`, `app/sync/mfa_login.py`, `app/sync/bootstrap_login.py`, and
`app/mfa_web/server.py` were all rewritten against `python-garminconnect`'s `Garmin`/`Client`
API. The MFA-marker no-retry-storm behavior described above, and the cached-session-first login
ordering, were both carried over unchanged in spirit onto the new library (`Client.load()` +
`Client.is_authenticated` in place of `garmy`'s `AuthClient.is_authenticated`/`refresh_tokens()`).

This couldn't be verified end-to-end against a live account from this sandboxed environment (no
route to `garmin.com` here) — a real, non-mocked standalone run of `python3 -m
app.sync.scheduler --once` proved the whole exception-wrapping chain works correctly (all 5 of
`python-garminconnect`'s login strategies executed in order, then a clean
`GarminConnectConnectionError` → `GarminAuthError` → `sync_log`-recorded failure, with no
unhandled crash), but the only failure it actually hit was this sandbox's own outbound network
policy blocking `sso.garmin.com`, not a code defect.

**Confirmed working on a real HA install**: after fixing a separate packaging bug that had been
blocking every real test of this (the `mfa-web` service's `run` script wasn't exporting Garmin
credentials at all — see the changelog), login through the ingress web UI completed
successfully. Logs showed exactly the cascading behavior the library is designed for: the
`mobile+cffi` and `mobile+requests` strategies both returned `429` (IP rate-limited by Garmin,
most likely from repeated logins during this debugging process), and the chain fell through to a
later strategy, which succeeded — no code change needed, this is the fallback working as
intended. Because a valid session is now cached, scheduled syncs won't re-attempt any login
strategy (rate-limited or not) until that session actually needs a fresh login again. This closes
out the migration: `python-garminconnect` does get past Garmin's Cloudflare challenge where three
fixes on top of `garmy` did not.

**Watch item, unconfirmed against `python-garminconnect`:** a separate, newer Garmin-side auth
problem surfaced in the wider unofficial-client ecosystem starting ~June 2026 —
[python-garminconnect#369](https://github.com/cyberjunky/python-garminconnect/issues/369) and
[garth#137](https://github.com/matin/garth/issues/137) both report login succeeding but a
subsequent API call returning `401 Token is not active`, suggesting Garmin changed server-side
bearer-token validation. No confirmed reports against the current `python-garminconnect` release
as of this writing, and this environment has no route to `garmin.com` to check directly — worth a
quick look if sync starts failing with a 401 after a successful-looking login (as opposed to the
MFA case above, which fails *during* login).

---

## 2. MCP Connection

StrideSync's MCP server is **read-only** — no write-back to Garmin Connect is planned for any
milestone below. Point an MCP client at the add-on's Streamable HTTP endpoint:

```
http://homeassistant.local:8765/mcp
```

(replace `homeassistant.local` with your HA server's hostname/IP, and `8765` with `mcp_port` if
you changed it from the default).

### Claude Desktop configuration

Claude Desktop speaks MCP over stdio to locally-launched processes, so connecting to a *remote*
Streamable HTTP server goes through `mcp-proxy` running as a local stdio↔HTTP bridge on your
machine (distinct from the `mcp-proxy` instance running *inside* the add-on, which bridges the
add-on's internal stdio-based MCP server to HTTP for the network hop):

```json
{
  "mcpServers": {
    "stridesync": {
      "command": "mcp-proxy",
      "args": [
        "http://homeassistant.local:8765/mcp"
      ]
    }
  }
}
```

Add this to Claude Desktop's `claude_desktop_config.json`, restart Claude Desktop, and StrideSync's
tools/resources should appear in a new conversation. See `DOCS.md`'s "Connecting Claude to
StrideSync" section for the `mcp_auth_token` header variant and full walkthrough.

### Remote access beyond the LAN (e.g. Claude mobile via Cloudflare Tunnel)

Requested directly: reach the MCP server from Claude on Android via an existing Cloudflare
Tunnel (`cloudflared`) HA add-on install. Mechanically this needs only a tunnel public hostname
routed at `http://homeassistant.local:8765` (the MCP port, not the `8767` ingress port — that
serves the browser-only MFA login page).

**Confirmed (milestone v0.9): Claude's "Add custom connector" UI cannot send `mcp_auth_token` at
all.** v0.6 below shipped `mcp_auth_token` on the assumption that it was merely unconfirmed
whether Claude's connector UI could attach a custom `Authorization` header; verified since then
that it definitively cannot — the UI only offers OAuth (Client ID/Secret) or no auth, with no
field for a static bearer token (tracked upstream as a known gap, e.g.
`anthropics/claude-ai-mcp` issues #112 and #411). That means `mcp_auth_token` alone does **not**
protect a Cloudflare-Tunnel-exposed MCP endpoint against Claude's own official connector traffic,
which arrives with no auth header regardless. Real protection for this specific client has to
come from restricting *who can reach the tunnel hostname*, not from a header StrideSync checks —
see `DOCS.md`'s Cloudflare WAF IP-allowlist step (Anthropic's published MCP-connector egress
ranges) for the approach actually taken. `mcp_auth_token` is kept anyway as defense-in-depth
against any other client and in case Claude adds header support later — it still fully protects
the `mcp-proxy`/Claude-Desktop path (§2 above), since that's a local process that can send any
header.

Cloudflare Access alone (gating the tunnel hostname via Cloudflare's own Zero Trust login) was
considered and rejected as the *only* protection for the same underlying reason: it needs either
an interactive login (which Claude's connector, fetching server-side from Anthropic's own
infrastructure, can't complete) or a Cloudflare Access Service Token — and Service Tokens are
also delivered via custom headers (`CF-Access-Client-Id`/`CF-Access-Client-Secret`), which the
connector UI can't attach either. Cloudflare Access can still be layered on top for defense in
depth, but isn't relied on as the sole gate — an IP-range WAF rule is, since it doesn't depend on
the connecting client sending anything at all.

---

## 3. Milestones

### v0.1 — Manual sync, verify schema 🔄

- ✅ `app/sync/garmin_client.py`: authenticate against Garmin Connect via `garmy`, wrapped so
  callers only ever see `GarminAuthError`/`GarminAPIError` (never a raw `garmy` or `requests`
  exception — see the module docstring for why transport-level failures needed their own
  handling, not just `garmy`'s own exception types)
- ✅ SQLite schema defined and created on first run (`activities`, `activity_metrics` as a
  per-lap time-series table for HR & pace, `sync_log`) — see `app/db/schema.sql`
- ✅ Manual sync runnable via CLI inside the container (`python3 -m app.sync.scheduler --once`)
  for verifying auth + schema without waiting on the scheduler
- ⬜ Inspect the resulting SQLite DB by hand to confirm the schema captures cadence, pace, HR,
  and training load fields Garmin actually returns — **still open**. `garmy`'s built-in
  activity summary has no distance/pace/cadence fields at all, so `garmin_client.py` merges it
  with the raw `/activity-service/activity/{id}` and `/activity-service/activity/{id}/splits`
  endpoints; the exact field names there (`summaryDTO`, `lapDTOs`, `averageRunningCadence...`)
  are inferred from the wider Garmin Connect tooling ecosystem, not confirmed against a live
  account — this dev environment has no route to `garmin.com` and no test credentials. Run
  `python3 -m app.sync.scheduler --once` against a real account and check
  `sqlite3 /data/stridesync.db` before ticking this off; adjust the field lookups in
  `garmin_client.py` if any come back `NULL` that shouldn't.
- ✅ CI pipeline (`.github/workflows/ci.yml`): yamllint + hadolint + version-ordering check +
  Python syntax check + `pytest` + Docker build smoke test on every push/PR
- ✅ Release pipeline (`.github/workflows/release.yml`): tags `stridesync/NEXT_VERSION`, builds
  and pushes multi-arch (`amd64`/`aarch64`) images to GHCR, creates a GitHub release, and opens
  the `chore/post-release` PR — see `CLAUDE.md`'s CI / Release section. Not yet run for a real
  release (that's v1.0's last checkbox).

### v0.2 — Scheduled sync service 🔄

- ✅ `rootfs/etc/services.d/sync-scheduler/run` — s6 service wrapping the scheduler loop
  (`app/sync/scheduler.py`'s `run_forever`), now exporting `garmin_username`/`garmin_password`/
  `sync_interval_hours`/`log_level` from `bashio::config` as env vars
- ✅ `sync_interval_hours` read from `/data/options.json` via `bashio::config`, default `6`
- 🔄 Sync runs continuously without manual invocation — verified by running
  `python3 -m app.sync.scheduler` directly (env vars set the way the s6 `run` script sets them)
  and confirming repeated sync passes + a clean exit within seconds of `SIGTERM` (not a multi-hour
  hang). **This caveat turned out to matter, twice**: `v0.1.0` shipped with a Dockerfile bug
  (`COPY app/ .` flattened the `app/` package into `WORKDIR`, breaking `python3 -m app.xxx` for
  both services — `ModuleNotFoundError: No module named 'app'`) that only running-from-`stridesync/`
  local testing could never have caught, because locally `app/` is naturally a subdirectory.
  Fixed (`COPY app/ ./app/`), and CI's Docker build test now actually **runs** the built image
  and checks both services start, not just that the image builds. That new CI smoke test
  immediately caught a **second** bug on the same PR: `00-validate-config.sh` used
  `bashio::config.has_value`, which calls out to the Supervisor API and always reports values
  missing when there's no real Supervisor (standalone `docker run`) — it would have killed the
  container even with a correct `options.json`. Fixed (plain `bashio::config` + a shell
  emptiness check, matching the pattern the service `run` scripts already used successfully). A
  real HA instance / `docker restart` still hasn't been exercised (no Docker daemon in this
  sandbox); verify there before the next stable release if possible.
- ✅ `sync_log` populated on every run (success and failure paths) — covered by
  `tests/test_scheduler.py::TestRunForever`
- ✅ Graceful failure path exercised: a forced Garmin login failure (real SSO call blocked by this
  sandbox's network policy) confirmed the loop logs the failure, writes it to `sync_log`, and
  keeps running rather than crashing the service — both as a unit test
  (`test_auth_failure_does_not_crash_the_loop`) and live via the CLI

### v0.3 — MCP server over HTTP 🔄

- ✅ `app/mcp/server.py` — built directly on `fastmcp`, wired to the sync scheduler's SQLite DB
  over a read-only connection (see Architecture §1 for why `garmy-mcp`'s bundled server wasn't
  reused as-is)
- ✅ Streamable HTTP on `mcp_port` (default `8765`), served natively by `fastmcp`
  (`transport="http"`) — no `mcp-proxy` process runs inside the add-on (see Architecture §1)
- ✅ `rootfs/etc/services.d/mcp-server/run` — s6 service for the MCP server, independent of
  `sync-scheduler`, now exporting `mcp_port`/`log_level` from `bashio::config`
- 🔄 Tested end-to-end **with a real MCP client over real Streamable HTTP** (`fastmcp.Client`
  connecting to a live `python3 -m app.mcp.server` subprocess, listing tools and calling all
  five) — confirmed the full wire protocol works. **Not tested with Claude Desktop itself** — no
  desktop environment in this sandbox to run it; the config snippet in §2 is unverified against
  the real client.
- ✅ MCP tools cover: recent activities (`recent_activities`), pace/cadence/HR trend over a date
  range (`pace_cadence_hr_trend`), training load summary (`training_load_summary`), and
  last-sync status (`last_sync_status`) — plus `activity_laps` for per-lap detail within one
  activity

### v0.4 — HA Supervisor add-on packaging 🔄

- ✅ `stridesync/config.yaml` finalized: `options` + `schema` for all five settings in §1
- ✅ `stridesync/build.yaml` multi-arch (`aarch64`, `amd64`) pinned to a specific
  `ghcr.io/hassio-addons/base` tag (`18.0.1`) — implicitly verified: CI's Docker build test job
  has been building against this exact tag since v0.1 and passing on every PR
- ✅ `icon.png` (128×128) and `logo.png` (250×100) — a simple generated runner-glyph placeholder
  (flat teal background, white pictogram, "StrideSync" wordmark on the logo), replacing the 1×1
  scaffolding PNGs. Not professional artwork — reasonable to swap for real branding later, but no
  longer a placeholder that would look broken in the add-on store.
- ✅ Ingress: **revisited and added**, for exactly one browser-facing page — the one-time Garmin
  MFA login (`app/mfa_web/server.py`, see §1's "Known risk" section), for HA users without
  terminal/`docker exec` access. Originally skipped in this milestone (MCP clients reach the MCP
  server directly over the network, not through HA's UI, so ingress didn't fit that connection
  model) — that reasoning still holds for the MCP server itself, which has no ingress route.
- 🔄 `repository.yaml` is present and yamllint-clean, but **not verified against a real HA
  instance** — this sandbox has no Home Assistant Supervisor to add the repository to. Add
  `https://github.com/nsaputro/stride-sync` under **Settings → Add-ons → Add-on Store → ⋮ →
  Repositories** on a real HA instance to confirm HA recognizes it as a valid add-on source.
- ⬜ Full install-from-repository flow — **not done**. Needs a real HA instance and (until a
  release is tagged, see v1.0) a locally built image, since `stridesync/config.yaml`'s `image:`
  field points at a GHCR path with no pushed images yet. This is the main remaining gap before
  the add-on can genuinely be called "released" — see the Getting Started section for the
  standalone `docker build`/`docker run` steps that substitute for it pre-release.

### v0.5 — Training baseline & effort granularity for marathon pacing 🔄

Average pace/HR per activity (v0.1–v0.3) answers "was this run fast or slow," but not "was this
the *right* effort for a marathon-training plan" — that needs a physiological reference point
(what's this athlete's threshold?) and, ideally, effort *distribution* within a run, not just its
average. Requested directly by the account owner after reviewing the synced data for exactly
this use case (target pacing, target HR). See §1's Garmin Connect sync section for the concrete
gap analysis that led to this scope.

- ✅ `training_baseline` table (single row, replaced each sync): lactate threshold HR/pace
  (`Client.get_lactate_threshold(latest=True)`) and Garmin's own 5k/10k/half/marathon race
  predictions (`Client.get_race_predictions()`) — fetched once per sync, not per activity. This
  is the reference point everything else (is 165bpm easy or hard for *this* person?) gets
  computed against.
- ✅ `activity_hr_zones` table: seconds spent in each HR zone per activity
  (`Client.get_activity_hr_in_timezones(activity_id)`) — one extra call per activity per sync,
  same call pattern as the existing per-activity laps fetch.
- ✅ `activity_samples` table: fine-grained time-series per activity (pace/HR/cadence/elevation
  at up to ~2000 points, from `Client.get_activity_details(activity_id)`) — enables cardiac-drift
  and negative-split detection at a finer resolution than 1km auto-lap splits.
- ✅ New MCP tools exposing all three (`training_baseline`, `activity_hr_zones`,
  `activity_samples` — the last one evenly downsampled to a `max_points` cap rather than dumping
  up to 2000 raw rows into a single tool response), so Claude can reason over target pace/HR in
  conversation rather than this codebase baking in training-science formulas itself (matches the
  existing philosophy: purpose-built data access, not opinionated analysis logic server-side).
- ⬜ Field mappings for all three endpoints are **best-effort, not yet verified against a live
  account** — same caveat as v0.1's still-open item for the activity-list endpoint. None of
  these three endpoints are normalized by `python-garminconnect` itself (all return raw
  `connectapi()` JSON), so the exact key names are inferred from the wider Garmin Connect tooling
  ecosystem. Verify against a real account and adjust field lookups if anything comes back
  unexpectedly `NULL`.
- ✅ Not every Garmin device/account has lactate-threshold or race-prediction data (e.g.
  non-running-focused watches) — confirmed this must degrade gracefully (log + store nothing)
  rather than fail the whole sync, unlike a genuine auth/network failure. `GarminClient`'s three
  new `fetch_*` methods for this milestone catch broadly and return `None`/`[]` rather than
  raising, unlike every other `fetch_*` method on the class — documented inline on each.

### v0.6 — Optional MCP auth for remote/internet exposure 🔄

Requested directly: reach the MCP server from Claude on Android through an existing Cloudflare
Tunnel add-on install. The MCP server (§2) was always designed to be reachable remotely, but
"remotely" meant "your LAN" until now — with zero auth, exposing it beyond the LAN would let
anyone who finds the URL read personal Garmin activity/HR/health data. See §2's "Remote access
beyond the LAN" subsection for the full reasoning on why this is enforced inside StrideSync
itself rather than relied on Cloudflare Access alone.

- ✅ New `mcp_auth_token` add-on option (`password` schema, optional, default `""` = disabled) —
  existing LAN-only installs keep working unchanged; sync-scheduler/mfa-web are unaffected (only
  the MCP server route needs gating).
- ✅ `SharedSecretVerifier` (`app/mcp/server.py`), a minimal `fastmcp.server.auth.TokenVerifier`
  subclass doing a constant-time (`hmac.compare_digest`) comparison against the configured token
  — wired into `FastMCP(auth=...)` only when `mcp_auth_token` is set. `create_server()` logs a
  clear warning when it isn't, so running unauthenticated is a visible choice, not a silent one.
- ✅ Confirmed real enforcement over an actual ASGI request/response cycle (not just
  `verify_token()` in isolation): no `Authorization` header → `401`, wrong token → `401`, correct
  token → passes through to normal MCP protocol handling. Exercised directly against
  `FastMCP.http_app()` via Starlette's `TestClient` in `tests/test_mcp_server.py`.
- ✅ `DOCS.md` documents the Cloudflare Tunnel setup (route the tunnel at `mcp_port`/`8765`, not
  the ingress port `8767`) and configuring an MCP client's bearer-token auth against the new
  option.
- ✅ Whether Claude's custom-connector UI (web/Desktop/Android) supports attaching a bearer token
  / custom `Authorization` header to a remote MCP connection — the open question this milestone
  originally left unconfirmed — was resolved (in the negative) during milestone v0.9's
  documentation work: it does not, and only supports OAuth or no auth. See v0.9's "Remote access
  beyond the LAN" note in §2 for the real mitigation (a Cloudflare WAF IP allowlist) since
  `mcp_auth_token` alone can't gate Claude's own connector traffic.

### v0.7 — "Running" tab: weekly mileage on the web UI 🔄

Requested directly, as a first step toward the web UI showing more than login/sync status.

- ✅ Tab navigation (`Dashboard` / `Running`) added to every page of the ingress web UI, not just
  the index page — a `_page()` parameter (`active_tab`) rather than a per-route special case.
- ✅ `/running` route: total distance per calendar week (Monday–Sunday), most recent week first.
  Grouped in Python (`date.weekday()`), not via SQLite date modifiers — deliberately, to keep the
  "which Monday does this date belong to" logic easy to verify by inspection rather than trusting
  a `strftime`/`'weekday N'` expression to be exactly right.
- ✅ Graceful degradation matches the rest of this module: no DB yet → empty list, not a crash;
  a malformed `start_time_local` on one row is skipped rather than failing the whole page; a
  missing `distance_meters` counts as 0 toward that week's total rather than crashing.

### v0.8 — Settings tab: one-off backfill from a start date 🔄

Requested directly, after clarifying that regular syncs are count-based (top N most recent
activities, see `GarminClient.fetch_recent_activities`) rather than date-based — there was no way
to pull in older history beyond whatever `limit` happens to cover.

- ✅ New `Settings` tab (third nav tab, alongside `Dashboard`/`Running`) with a date picker +
  "Backfill" button.
- ✅ `GarminClient.fetch_activities_since(start_date)` — uses
  `Client.get_activities_by_date(startdate)` (genuinely date-based, auto-paginating in Garmin's
  own library, unlike the count-based `get_activities` regular syncs use) — merged with the same
  per-activity detail (`_merge_with_detail`, extracted from `fetch_recent_activities` to be
  shared rather than duplicated).
- ✅ `scheduler.run_backfill_sync(settings, client, start_date)` — a separate entry point from
  `run_sync_once`, sharing the actual per-activity write loop via a new `_sync_activities`
  generator (yields once per completed activity, so partial progress is still counted/logged
  correctly even if a later activity's fetch fails partway through — the same behavior
  `run_sync_once` already had, now shared instead of duplicated). Does not refresh
  `training_baseline` — that stays the regular scheduled sync's job.
- ✅ A bad start date raises a plain `ValueError` (from `python-garminconnect`'s own date-format
  validation, before any network call) rather than a `GarminAPIError` — deliberately not logged
  to `sync_log` as a failed sync attempt, since it's caller-input validation, not a real sync
  failure. The web UI catches it separately with a clear "Invalid start date" message.
- ✅ **Live progress bar**, added after confirming a multi-year backfill covers hundreds of
  activities and can genuinely take a long time (many Garmin API calls — each activity costs 4:
  detail, laps, HR zones, samples). The original design ran the whole backfill synchronously
  inside the request handler (same "blocking call in an async handler" pattern as the "Sync now"
  button) — fine for a normal sync's fixed top-20, but a poor fit here since there's no way to
  report progress mid-request on a single request/response cycle. Reworked to run
  `run_backfill_sync` on a background thread (`POST /backfill` starts it and returns
  immediately), with `GET /backfill` showing a live `<progress>` bar that polls a new
  `GET /backfill/status` JSON endpoint roughly once a second. `run_backfill_sync` gained an
  optional `progress_callback(completed, total)` parameter for this — called once immediately
  after the activity list is fetched (so the bar's total is correct from the start) and once per
  completed activity.
- ✅ Only one backfill runs at a time (matches this add-on's single-account design) — a second
  `POST /backfill` while one is already running is a no-op that just shows the existing one's
  progress, rather than starting a second background thread against the same Garmin account.
  Caught and fixed a real self-deadlock here during development: the "already running" branch
  originally called `_backfill_progress_body()` (which acquires `_backfill_lock`) from inside a
  `with _backfill_lock:` block already holding that same non-reentrant lock — reproduced via a
  real test hang (not just a review-time guess), fixed by moving that call outside the lock's
  scope.
- ✅ **Fixed a real production `sqlite3.OperationalError: database is locked` crash**, reported
  live: the backfill's write connection (`app/db/connect`) stays open across hundreds of commits,
  and the **Running** tab's read hit the DB at just the wrong moment and crashed with a 500.
  Root cause was SQLite's default rollback-journal mode having no built-in tolerance for a reader
  landing mid-write — any read during the writer's brief exclusive-lock window at commit time
  fails immediately instead of waiting. Fixed by switching `/data/stridesync.db` to WAL mode
  (readers and the one writer never block each other under WAL) plus a 5s busy-timeout on every
  connection as defense-in-depth. Reproduced deterministically in
  `tests/test_db.py::test_readonly_reader_does_not_block_writer_in_wal_mode` (a reader holding an
  open transaction blocks the writer's commit without the fix, confirmed by reverting it and
  watching the test fail with the exact same exception before re-applying).
- ✅ **Fixed the progress bar disappearing on tab-switch**, also reported live: the "Settings" nav
  tab (`GET /settings`) always rendered the static backfill form regardless of `_backfill_state`,
  so switching to another tab mid-backfill and clicking back into Settings replaced the live
  progress bar with the plain form again — the backfill kept running server-side the whole time,
  but there was no way to see it short of navigating directly to `/backfill`. `_settings_body()`
  now checks `_backfill_state` itself: shows the progress bar while running, the last backfill's
  result/error (plus the form, so a new one can still be started) once done, otherwise the plain
  form as before.

### v0.9 — Claude connection docs: Desktop direct + mobile via Cloudflare Tunnel, example prompts 🔄

Requested directly: documentation for connecting Claude Desktop (direct LAN) and Claude mobile
(via an existing Cloudflare Tunnel install), plus example prompts for run analysis and
training-pace recommendations.

- ✅ `DOCS.md`'s "Connecting Claude to StrideSync" section rewritten into two concrete setups:
  Claude Desktop (`claude_desktop_config.json` + `mcp-proxy` stdio↔HTTP bridge, since that's a
  local process on the user's own machine and so can reach a LAN-only hostname) and Claude mobile
  (Settings → Connectors → Add custom connector, since mobile/claude.ai fetch remote MCP servers
  from Anthropic's own cloud infrastructure rather than the user's device, requiring a public
  URL).
- ✅ **Discovered and documented a real client-side limitation** while researching the mobile
  setup: Claude's "Add custom connector" UI only supports OAuth or no authentication — there is no
  field for a static bearer token, so it cannot send StrideSync's `mcp_auth_token` header at all.
  This resolves v0.6's previously-open question in the negative (see that milestone's updated
  bullet) and means `mcp_auth_token` alone does not protect a Cloudflare-Tunnel-exposed endpoint
  against Claude's own connector traffic.
- ✅ Verified Anthropic publishes a fixed outbound IP range for MCP-connector fetches
  (`160.79.104.0/21` IPv4, `2607:6bc0::/48` IPv6, per
  [Anthropic's IP-address reference](https://platform.claude.com/docs/en/api/ip-addresses)) —
  real, checkable access control that doesn't depend on the connecting client sending any header.
  `DOCS.md` documents adding a Cloudflare WAF rule restricting the tunnel hostname to these
  ranges, chosen over the weaker "obscure hostname only" alternative after asking directly.
  `mcp_auth_token` is kept regardless, as defense-in-depth against any other client and since it
  still fully protects the Desktop/`mcp-proxy` path (a local process can send any header).
- ✅ New "Example prompts" section in `DOCS.md`: recent-run review, trend analysis over time,
  and racing/target-pace prompts for easy/long/threshold/interval training types — grounded in
  the actual MCP tools this add-on exposes (`training_baseline`'s lactate-threshold pace/HR and
  race predictions, `pace_cadence_hr_trend`, `training_load_summary`), not generic examples
  disconnected from what StrideSync can actually answer.

### v1.0 — Documented, versioned, changelog-tracked release 🔄

- ✅ `DOCS.md` complete: install steps, all config options (now six, since milestone v0.6 added
  `mcp_auth_token`), MCP connection instructions (`http://homeassistant.local:8765/mcp`), and the
  known-risk note about Garmin auth breakage
- ✅ `README.md` complete: accurate status (v0.1–v0.4 implemented, nothing released yet), a
  standalone Quick Start (`docker build`/`docker run`, no HA instance required), install
  instructions, config table, and the known-risk note
- ✅ `CHANGELOG.md` (root) and `stridesync/CHANGELOG.md` (add-on-local) populated for every
  milestone under `## [Unreleased]`, in Keep a Changelog format
- ✅ `stridesync/config.yaml` `version` (`0.0.0` — no release has shipped) and
  `stridesync/NEXT_VERSION` (`0.1.0` — next version to release) follow the versioning convention
  in `CLAUDE.md`
- ✅ Fixed a real bug in `.github/workflows/release.yml`'s post-release changelog script before
  it ever ran for real: simulated it against this repo's actual `CHANGELOG.md` and found the
  first-ever release (no prior version section, no prior git tag) both 404'd its own comparison
  link (`compare/v0.0.0...vX.Y.Z` — that tag was never created) and duplicated the version's
  trailing reference link in the generated `stridesync/CHANGELOG.md`. Fixed both; re-simulated a
  first release *and* a hypothetical second release (with a real prior tag) to confirm both
  paths now produce correct output.
- ⬜ First tagged GitHub release, images published to GHCR for `amd64` + `aarch64` — **not done,
  intentionally**. Running the release workflow publishes real public Docker images and a real
  GitHub release; that's a judgment call about readiness for the repo owner to make, not
  something to trigger unprompted. Once `stridesync/NEXT_VERSION` (`0.1.0`) is confirmed correct:
  **Actions → Release → Run workflow** on `main`. See `CLAUDE.md`'s CI / Release section.

---

## Getting Started (Development)

### Prerequisites

- Python 3.12+
- Docker

### Build & run the add-on standalone

See **Local Development & Testing** in `CLAUDE.md` for the full standalone `docker build` /
`docker run` walkthrough — you do not need a Home Assistant instance until milestone v0.4.

### Manual sync (v0.1+)

```bash
cd stridesync
pip install -r app/requirements.txt
python3 -m app.sync.scheduler --once   # one-shot sync, doesn't wait for the interval
```

### HA Add-on Installation (once published, v0.4+)

1. Settings → Add-ons → Add-on Store → ⋮ → Repositories
2. Add: `https://github.com/nsaputro/stride-sync`
3. Find **StrideSync** → Install → Configure Garmin credentials → Start

---

_Own your training data — talk to it 🏃_
