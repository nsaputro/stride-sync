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
  need explicit user confirmation flows and is out of scope for Stage 19).

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
(`ingress: true`/`ingress_port` in `config.yaml`, revisiting the Stage 4 milestone's original "no
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

**Confirmed (milestone Stage 9): Claude's "Add custom connector" UI cannot send `mcp_auth_token` at
all.** Stage 6 below shipped `mcp_auth_token` on the assumption that it was merely unconfirmed
whether Claude's connector UI could attach a custom `Authorization` header; verified since then
that it definitively cannot — the UI only offers OAuth (Client ID/Secret) or no auth, with no
field for a static bearer token (tracked upstream as a known gap, e.g.
`anthropics/claude-ai-mcp` issues #112 and #411). There is only one MCP server (and one
`mcp_auth_token` setting) regardless of whether a request arrives over the LAN or through the
tunnel, and `SharedSecretVerifier` rejects any request without a valid token when it's set (see
Stage 6 below) — so this isn't "set it anyway, it can only help": if `mcp_auth_token` is set,
**every** request from Claude's own connector gets `401`'d too, since it can never send one.
Setting `mcp_auth_token` and getting Claude's official mobile connector to work are mutually
exclusive on the same server. `DOCS.md` documents leaving `mcp_auth_token` empty for this path
and relying entirely on a Cloudflare WAF rule restricting the tunnel hostname to Anthropic's
published MCP-connector egress ranges instead — the only access control left once the token is
disabled for the connector's sake. `mcp_auth_token` remains worth setting for installs that only
use the `mcp-proxy`/Claude-Desktop path (§2 above) and don't need Claude's official mobile
connector at all — that path is a local process and can send any header — but it's an either/or
choice per install, not both at once.

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

### Stage 1 — Manual sync, verify schema 🔄

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
  release (that's Stage 19's last checkbox).

### Stage 2 — Scheduled sync service 🔄

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

### Stage 3 — MCP server over HTTP 🔄

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

### Stage 4 — HA Supervisor add-on packaging 🔄

- ✅ `stridesync/config.yaml` finalized: `options` + `schema` for all five settings in §1
- ✅ `stridesync/build.yaml` multi-arch (`aarch64`, `amd64`) pinned to a specific
  `ghcr.io/hassio-addons/base` tag (`18.0.1`) — implicitly verified: CI's Docker build test job
  has been building against this exact tag since Stage 1 and passing on every PR
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
  release is tagged, see Stage 19) a locally built image, since `stridesync/config.yaml`'s `image:`
  field points at a GHCR path with no pushed images yet. This is the main remaining gap before
  the add-on can genuinely be called "released" — see the Getting Started section for the
  standalone `docker build`/`docker run` steps that substitute for it pre-release.

### Stage 5 — Training baseline & effort granularity for marathon pacing 🔄

Average pace/HR per activity (Stage 1–Stage 3) answers "was this run fast or slow," but not "was this
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
  account** — same caveat as Stage 1's still-open item for the activity-list endpoint. None of
  these three endpoints are normalized by `python-garminconnect` itself (all return raw
  `connectapi()` JSON), so the exact key names are inferred from the wider Garmin Connect tooling
  ecosystem. Verify against a real account and adjust field lookups if anything comes back
  unexpectedly `NULL`.
- ✅ Not every Garmin device/account has lactate-threshold or race-prediction data (e.g.
  non-running-focused watches) — confirmed this must degrade gracefully (log + store nothing)
  rather than fail the whole sync, unlike a genuine auth/network failure. `GarminClient`'s three
  new `fetch_*` methods for this milestone catch broadly and return `None`/`[]` rather than
  raising, unlike every other `fetch_*` method on the class — documented inline on each.

### Stage 6 — Optional MCP auth for remote/internet exposure 🔄

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
  originally left unconfirmed — was resolved (in the negative) during milestone Stage 9's
  documentation work: it does not, and only supports OAuth or no auth. See Stage 9's "Remote access
  beyond the LAN" note in §2 for the real mitigation (a Cloudflare WAF IP allowlist) since
  `mcp_auth_token` alone can't gate Claude's own connector traffic.

### Stage 7 — "Running" tab: weekly mileage on the web UI 🔄

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

### Stage 8 — Settings tab: one-off backfill from a start date 🔄

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

### Stage 9 — Claude connection docs: Desktop direct + mobile via Cloudflare Tunnel, example prompts 🔄

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
  This resolves Stage 6's previously-open question in the negative (see that milestone's updated
  bullet) and means `mcp_auth_token` alone does not protect a Cloudflare-Tunnel-exposed endpoint
  against Claude's own connector traffic.
- ✅ Verified Anthropic publishes a fixed outbound IP range for MCP-connector fetches
  (`160.79.104.0/21` IPv4, `2607:6bc0::/48` IPv6, per
  [Anthropic's IP-address reference](https://platform.claude.com/docs/en/api/ip-addresses)) —
  real, checkable access control that doesn't depend on the connecting client sending any header.
  `DOCS.md` documents adding a Cloudflare WAF rule restricting the tunnel hostname to these
  ranges, chosen over the weaker "obscure hostname only" alternative after asking directly. This
  is the *only* protection on this path — `mcp_auth_token` must be left empty for Claude's
  connector to work at all (there's one server-wide setting, and it 401's every request without
  a token, including the connector's own), so it isn't "defense-in-depth on top of" the WAF rule
  here. `mcp_auth_token` is still worth setting for installs that only use the
  Desktop/`mcp-proxy` path and don't need Claude's official mobile connector — but that's an
  either/or choice per install, not both at once.
- ✅ New "Example prompts" section in `DOCS.md`: recent-run review, trend analysis over time,
  and racing/target-pace prompts for easy/long/threshold/interval training types — grounded in
  the actual MCP tools this add-on exposes (`training_baseline`'s lactate-threshold pace/HR and
  race predictions, `pace_cadence_hr_trend`, `training_load_summary`), not generic examples
  disconnected from what StrideSync can actually answer.
- ✅ **Example Claude Skill added** (follow-up, user-provided): `docs/skills/running-coach/`
  — a `SKILL.md` turning the raw MCP tools above into a structured running-coaching workflow
  (race-target tracking against Claude's memory, training-progression checks combining load/
  long-run/weekly-mileage trends with `daily_wellness` recovery signals, target-pace/HR lookups,
  and lap-level analysis that correctly separates structured-workout work-rep pace from recovery
  jogs instead of using a misleading whole-session average). `docs/skills/README.md` explains
  what a Skill is and how to install one; both `README.md` and `DOCS.md`'s "Example prompts"
  section link to it. Purely additive documentation — no application code changed, entirely
  optional to use.

### Stage 10 — Fix: "Log in again" silently resumed the cached session instead of re-authenticating 🔄

Found live while walking through the Stage 9 Cloudflare Tunnel setup end-to-end: once the tunnel
was working, a display-name profile issue led to trying "Log in again" on an MFA-enabled
account, which never showed the MFA prompt at all — clicking it appeared to do nothing.

- ✅ **Root-caused via the installed `garminconnect` library's actual source**: `Garmin.login()`
  does `tokenstore = tokenstore or os.getenv("GARMINTOKENS")`, then tries to resume a session
  from that tokenstore before ever attempting a credentials-based login — and only a
  credentials-based login can trigger an MFA challenge. Since `mfa_login.start_login()` always
  passed the real `token_dir`, a still-valid cached session was silently resumed every time,
  regardless of the user's intent, so "Log in again" was a no-op whenever a session already
  existed — exactly backwards from what the button's label promises.
- ✅ `mfa_login.start_login()` gained a `force: bool = False` parameter: when true, passes
  `tokenstore=None` instead of `token_dir`, so `Garmin.login()` has nothing to resume from and
  always performs a full credentials login (triggering MFA if the account requires it).
  Deliberately does **not** delete the cached session up front — `_persist_session()` only
  overwrites `token_dir` on a *successful* new login, so a failed forced re-login (bad
  credentials, Garmin unreachable) leaves the old, still-working session in place for the sync
  scheduler rather than leaving the account logged out entirely.
- ✅ `app/mfa_web/server.py`'s `start()` route sets `force=True` whenever
  `_has_cached_session(settings.garmin_token_dir)` is true — i.e. exactly the "Log in again"
  case (see `_status_body`) — and leaves it `False` for a first-ever login, where there's
  nothing to resume anyway. Button label updated to "Log in again (forces a fresh login,
  including MFA if required)" so the behavior is self-explanatory.
- ✅ Verified the fix actually discriminates: reverted it locally and confirmed the new tests
  fail with the literal wrong call (`login(tokenstore='<real token dir>')` instead of
  `login(tokenstore=None)`), not just that they pass with the fix applied.
- ⬜ Separately investigated (not a StrideSync bug): the same live account also hit
  `GarminClient.fetch_training_baseline`'s "Display name is not set" warning even after setting
  a display name on connect.garmin.com and forcing a fresh login. Traced to
  `python-garminconnect`'s `_require_display_name()` reading `self.display_name`, populated from
  `prof.get("displayName", self.username)` on Garmin's `/userprofile-service/socialProfile`
  response — `dict.get(key, default)` only falls back when the key is *absent*, not when
  present with an explicit `null`, so this looks like a Garmin-side data issue (or the account
  editing a different profile field than the one this specific endpoint reads), not something
  fixable from StrideSync's side. Left as a known, non-fatal, already-gracefully-handled
  limitation (milestone Stage 5) rather than a bug to chase further here.

### Stage 11 — Temperature in per-activity time-series samples 🔄

Requested directly: is temperature synced with activity data? It wasn't — checked the schema and
sync code and confirmed no temperature field existed anywhere, despite Garmin's per-second chart
data (already fetched for `activity_samples`, milestone Stage 5) including it for devices that
record it.

- ✅ New `temperature_celsius` field: `ActivitySample` dataclass, `_SAMPLE_METRIC_KEYS` gains
  `"temperature_celsius": ("directTemperature",)` (same "direct"-prefixed chart-data key
  convention as `directHeartRate`/`directSpeed`/`directElevation` already in use, inferred from
  the wider Garmin Connect tooling ecosystem, not yet confirmed against a live account — same
  caveat as the rest of this metric-key table), `activity_samples` table column, and the
  `activity_samples` MCP tool's SELECT — nullable throughout, same graceful-degradation pattern
  as every other sample field for a device/activity that doesn't report it.
- ✅ **Real schema-migration gap found and fixed**: `activity_samples` already existed in shipped
  databases (unlike every previous milestone's schema addition, which was always a brand-new
  table `CREATE TABLE IF NOT EXISTS` handles for free) — adding a column to `schema.sql` alone is
  a no-op against an already-existing table, so every install upgrading from before this column
  existed would have started failing every sample INSERT with "table activity_samples has no
  column named temperature_celsius". Added `db._add_column_if_missing()`, called from `init_db()`
  on every startup (checks `PRAGMA table_info`, `ALTER TABLE ... ADD COLUMN` only if missing) —
  this is this codebase's first real column-migration, since nothing needed one before. Verified
  with a test that creates an old-shape `activity_samples` table by hand, connects through
  `db.connect()`, and confirms both the new column appears and pre-existing data survives
  untouched.

### Stage 12 — Recovery, readiness & training-plan signals 🔄

The existing MCP tools describe **what happened** in a run, but nothing captured
**recovery/readiness** — sleep, HRV, and Garmin's own training-readiness score are the earliest
signals of overreaching, ahead of it showing up as declining pace or rising HR at the same
effort in `pace_cadence_hr_trend`. Also adds persisted history for VO2 max and resting HR (both
previously only a point-in-time snapshot) and a planned-vs-actual workout comparison. Split
across three PRs for review size.

- ✅ `daily_wellness` table + `GarminClient.fetch_daily_wellness(cdate)`: sleep
  (`get_sleep_data`), HRV (`get_hrv_data`), training status (`get_training_status`), training
  readiness (`get_morning_training_readiness`), resting HR (`get_rhr_day`) — five
  independently-wrapped best-effort sub-fetches (not one shared try/except like
  `training_baseline`), since HRV/sleep/readiness support varies independently by device/account;
  one endpoint failing degrades only its own column(s) to `NULL`, not the whole day's row.
- ✅ Sync step fetches + upserts one `daily_wellness` row per calendar date for a rolling window
  (today back 3 days, `_WELLNESS_WINDOW_DAYS = 4`) on every `run_sync_once` call, ahead of the
  per-activity loop (same placement as `training_baseline`) — re-fetching/overwriting the same
  date on every sync catches Garmin finalizing sleep/HRV data a day late. `run_backfill_sync`
  does not touch this table, matching `training_baseline`'s existing precedent.
- ✅ Two new MCP tools: `daily_wellness(days=14)` and `resting_hr_trend(days=30)` (oldest-first
  `(calendar_date, resting_hr)` pairs, mirroring `pace_cadence_hr_trend`'s shape).
- ✅ `vo2max_history` table + `GarminClient.fetch_vo2max(cdate)` (`get_max_metrics`), same
  rolling-window daily-fetch pattern — additive to (not a replacement for) the existing
  `training_baseline` table/tool. New `vo2max_trend(days=90)` MCP tool.
- ✅ **VO2 max field mapping confirmed and fixed** (follow-up, via the new `vo2max` Diagnostics
  check): `get_max_metrics`'s real successful response is a *list* containing one dict, not a
  bare dict — the earlier crash-guard's "list means unexpected/no data" assumption was wrong and
  was silently discarding every real reading (rows still got inserted via `calendar_date`, but
  every numeric field came back `NULL` — this is what the dashboard's new per-record-type totals
  vs. `vo2max_trend`'s all-`null` MCP output exposed). `_normalize_vo2max` now unwraps that list;
  `generic.vo2MaxPreciseValue`/`vo2MaxValue` were already guessed right (confirmed:
  `55.2`/`55.0`), `fitnessAge` was fixed to look nested under `generic` instead of the top level.
  Also confirmed via the `hrv_data` Diagnostics check that `hrvSummary.status`/`weeklyAvg`/
  `lastNightAvg` were already guessed correctly — no fix needed there.
- ✅ `planned_workouts` table + `GarminClient.fetch_planned_workouts(start_date, end_date)`
  (`get_training_plans` + `get_training_plan_by_id` per plan) — delete-then-bulk-insert scoped to
  a rolling ±14-day window on every sync, since Garmin's training-plan response has no confirmed
  stable per-workout id to key an UPSERT on. Degrades to an empty list, not a sync failure, for
  the many accounts with no active plan. New `planned_vs_actual(days=14)` MCP tool (planned
  workout LEFT JOINed against `activities` by calendar date).
- ⬜ Field mappings for all six new/reused endpoints are **best-effort, not yet verified against
  a live account** — same caveat as Stage 1/Stage 5/Stage 11's still-open items. `get_rhr_day` and
  `get_sleep_data` both touch `self.display_name` internally, so the account already hitting
  Stage 10's known display-name gap may see `resting_hr`/sleep fields come back `NULL` specifically
  *because of that gap*, independent of whether the guessed JSON keys are right — check both
  possibilities before assuming a wrong field-name guess. The training-plan shape is still the
  least certain of the six — see Stage 15 for the first round of live-account fixes to it.
- ✅ Brand-new tables only (`daily_wellness`, `vo2max_history`, `planned_workouts`) — confirmed
  none of the three need `_add_column_if_missing`/`ALTER TABLE` migration code, unlike Stage 11's
  `temperature_celsius` (which added a column to an already-shipped table). `CREATE TABLE IF NOT
  EXISTS` in `schema.sql` is sufficient for every existing install.

### Stage 13 — Incremental activity sync + per-record-type sync log counts 🔄

Regular scheduled syncs (`run_sync_once`) always fetched a fixed most-recent-20 activities
(`GarminClient.fetch_recent_activities`) — a busy stretch (more than 20 activities logged since
the last sync) would silently miss activities older than the 20th-most-recent, with no way to
notice from the logs alone. Separately, the only per-sync signal available was a single
"N activities" count — confirming whether the new Stage 12 tables (`daily_wellness`,
`vo2max_history`, `planned_workouts`) actually got fresh data required a direct SQL query against
the database, rather than being visible from the add-on log alone.

- ✅ `run_sync_once` now fetches activities via `GarminClient.fetch_activities_since` (already
  used by `run_backfill_sync`) instead of `fetch_recent_activities`, using the most recent
  *successful* sync's date (`_last_successful_sync_date`, reading `sync_log.started_at` filtered
  to `status = 'success'`) as the start date — or `_FIRST_SYNC_LOOKBACK_DAYS` (7) days back if
  this account has never completed a successful sync yet. A failed sync is deliberately not
  treated as "last successful" so a retry re-covers the same range rather than skipping past
  whatever the failed attempt never actually synced. `fetch_recent_activities` itself is
  unchanged and still available on `GarminClient` (tested, just no longer called by the
  scheduler) — the now-meaningless `--limit` CLI flag and the `limit` parameter threaded through
  `run_sync_once`/`run_forever`/`main()` were removed instead of left as dead wiring.
- ✅ `run_sync_once` now logs a per-record-type count on both the success and failure path —
  activities, `daily_wellness` rows, `vo2max_history` rows (only counting ones where Garmin
  actually returned data, not every date in the window), and `planned_workouts` rows — so
  confirming what actually synced is a log line away instead of requiring a direct SQL query.
  This is a log-only change; `sync_log`'s schema is untouched.
- ✅ **Dashboard tab extended with the same per-record-type totals** (follow-up, requested
  live): `_sync_summary` (`app/mfa_web/server.py`) now also runs `COUNT(*)` against
  `daily_wellness`/`vo2max_history`/`planned_workouts`, alongside the existing
  `Total activities synced` stat — the dashboard previously only ever showed the activities
  count, even though the log lines above already reported all four. Plain `COUNT(*)` queries
  against current table contents, not a new `sync_log` column — no schema change.

### Stage 14 — Backfill parity with regular sync + a real infinite-backfill-loop bug fix 🔄

`run_backfill_sync` only ever wrote activities — `training_baseline`/`daily_wellness`/
`vo2max_history`/`planned_workouts` stayed the regular scheduled sync's job, so backfilling
historical data from before a Garmin account had wellness/VO2-max tracking enabled had no way to
also pull in that history. Separately, a live user reported the Settings tab's backfill button
looping forever — the add-on log showed the exact same `POST /backfill` → "succeeded: N
activities" repeating every second until the container was restarted.

- ✅ `run_backfill_sync` now also refreshes `training_baseline` (unconditional, same as
  `run_sync_once`) and fetches `daily_wellness`/`vo2max_history` for **every date from
  `start_date` through today** (not `run_sync_once`'s fixed `_WELLNESS_WINDOW_DAYS`-day rolling
  window) — covering the whole historical range is the entire point of a backfill. Confirmed via
  a real timing check that a 6-year day-by-day loop (`2020-01-01` → today, ~2380 iterations) adds
  only ~30ms — no need to worry about this being slow in practice, only the per-activity Garmin
  API calls are.
- ✅ `planned_workouts` is also refreshed on backfill, but — unlike wellness/vo2max — using the
  same fixed `[-_PLANNED_WORKOUT_LOOKBACK_DAYS, +_PLANNED_WORKOUT_LOOKAHEAD_DAYS]`-from-today
  window `run_sync_once` uses, regardless of `start_date`: a training plan is a forward-looking
  concept, not historical data a backfill would otherwise miss.
- ✅ `run_backfill_sync` logs per-record-type counts on success/failure too, matching Stage 13's
  `run_sync_once` change.
- ✅ **Root-caused and fixed the reported infinite-backfill-loop bug**: `app/mfa_web/server.py`'s
  backfill POST handler rendered the progress page directly (200 OK) instead of redirecting.
  `_BACKFILL_POLL_SCRIPT`'s `location.reload()` — called once the poller sees the backfill
  finish — reloads *whatever request produced the current page*, and in most browsers that means
  **re-submitting the original POST** when the current page was itself a direct POST response.
  Every time the poller noticed completion, `location.reload()` silently re-POSTed the same form,
  restarting the backfill, forever — exactly matching the reported log pattern. Fixed with the
  standard Post/Redirect/Get pattern: the POST handler now always issues a `303` redirect to the
  `GET /backfill` route instead of rendering the page itself, so the browser's last request for
  that URL is a GET, which `location.reload()` can safely re-issue. Verified with a live
  ASGI-level test client simulating repeated `location.reload()`-style reloads after the fix,
  confirming `run_backfill_sync` is invoked exactly once no matter how many times the page
  "reloads" afterward.

### Stage 15 — First live-account fix for planned_workouts 🔄

A live user reported an actual active Garmin training plan (screenshotted from the Garmin
Connect app's "Workout Schedule" view — named workouts like "Threshold"/"Base"/"Anaerobic"
assigned to specific calendar dates) producing "0 planned workouts" on both sync and backfill,
confirming the Stage 12 field-mapping caveat was right to flag this as the least-certain of the six
endpoints.

- ✅ **Confirmed and fixed a real bug**: `get_training_plans()`'s actual top-level key is
  `trainingPlanList`, not the `trainingPlans`/`plans` originally guessed — confirmed directly
  from `python-garminconnect`'s own bundled `demo.py` (`resp.get("trainingPlanList") or []`), not
  another guess. The old code's `_get(plans, "trainingPlans", "plans")` matched neither key, so
  `plan_list` fell through to `None` and `fetch_planned_workouts` returned `[]` silently on every
  sync — this alone plausibly explains the reported "0 planned workouts" outright. The old guesses
  are kept as lower-priority fallbacks in `_get()`'s candidate list in case this varies by API
  version.
- ✅ **Resolved the previously-open `get_adaptive_training_plan_by_id` question**: `demo.py`
  routes a plan whose `trainingPlanCategory` field equals `"FBT_ADAPTIVE"` to
  `get_adaptive_training_plan_by_id`, everything else to the phased `get_training_plan_by_id`.
  `fetch_planned_workouts` now checks this field per-plan and calls the matching endpoint.
- ⬜ The training-plan *detail* response's own shape (workout dates/names/target pace/HR, handled
  by `_normalize_planned_workouts`) is still unconfirmed — `python-garminconnect`'s own demo
  script only pretty-prints the raw response without field-level access, so no further
  confirmation was available from that source. Also discovered `get_scheduled_workouts(year,
  month)` (the calendar-service endpoint, `/calendar-service/year/{year}/month/{month-1}`) as a
  plausibly better-matched source for a literal "workout schedule by calendar date" view like the
  one screenshotted — but its response shape is equally unconfirmed. A diagnostic script covering
  both the training-plan detail endpoint and `get_scheduled_workouts` was sent to the reporting
  user; a follow-up fix once real output comes back. **Confirmed the `trainingPlanList` fix alone
  did not resolve the reported issue** (live re-test still shows `0 planned workouts`) — the
  remaining gap was one level deeper: **found and fixed in Stage 17** via the Stage 16 Diagnostics
  panel (a plan entry's own id field is `trainingPlanId`, not `planId`/`id`). The detail
  response's own shape (workout dates/names/target pace/HR) is *still* unconfirmed — that's the
  next thing Stage 17 needs live output for.

### Stage 16 — In-app Diagnostics panel for live-account troubleshooting 🔄

This session has now hit the same shape of live-account bug four times (temperature sample key
in Stage 11, `fetch_vo2max`'s list-vs-dict crash and `fetch_daily_wellness`'s identical gap in the
Stage 12 follow-up fix, `planned_workouts`'s `trainingPlanList` key in Stage 15) — each one required
handing the reporting user a one-off Python script to run via `docker exec`/`ha addons exec` just
to see the real Garmin API response shape. Building that capability into the add-on itself means
the next unconfirmed-field-mapping bug doesn't need a fresh script written and walked through
each time.

- ✅ New `GarminClient.fetch_diagnostic(check)` method + `DIAGNOSTIC_CHECKS` dict (id → human
  label) in `garmin_client.py`: returns the **raw, unnormalized** JSON response for one of a
  fixed, curated set of read-only checks (`training_plans`, `training_plan_detail`,
  `scheduled_workouts`) — deliberately not open to an arbitrary method name, since several
  `python-garminconnect` methods are write operations (`schedule_workout`, `upload_workout`,
  `delete_workout`, etc.) and StrideSync must never write back to Garmin (CLAUDE.md/README).
  Unlike every other `fetch_*` method, failures are **not** swallowed non-fatally — the caller
  wants to see the raw exception too, since "this endpoint failed with X" is itself useful
  diagnostic information.
- ✅ New "Diagnostics" section on the Settings tab: a dropdown (built straight from
  `DIAGNOSTIC_CHECKS`, so adding a future check is a one-line addition) + a button that POSTs to
  a new `/diagnostics` route, logs in, runs the selected check, and renders the exact JSON
  response (`json.dumps(..., indent=2)`, capped at `_DIAGNOSTIC_OUTPUT_LIMIT` — originally 8000
  chars, raised to 60000 in Stage 17 once that turned out too small in practice) directly in the
  page — no shell/docker access needed to report a wrong-looking field going forward.
- ✅ Verified end-to-end with a live ASGI test client: `/settings` shows the new dropdown, and a
  mocked `/diagnostics` POST renders the raw JSON in the response body.
- ✅ **Copy-to-clipboard button** on the diagnostic output (live feedback from the first real use
  of this panel: the JSON box was awkward to select/copy by hand for pasting into a bug report).
  `navigator.clipboard.writeText()` against the exact `<pre id="diagnostic-output">` text — not a
  re-serialized copy, so what gets pasted is byte-identical to what's displayed.
- ✅ **Extended `DIAGNOSTIC_CHECKS` to the `daily_wellness`/`vo2max_history` endpoints**:
  `sleep_data`, `hrv_data`, `training_status`, `training_readiness`, `resting_hr`, `vo2max` —
  live report that an account with real VO2 max and HRV history in the Garmin Connect app was
  getting `NULL` for both in StrideSync, the same wrong-field-name-guess failure class as
  `planned_workouts`, just not yet pinned to a specific key. These six checks expose the raw
  response for each of `fetch_daily_wellness`'s five sub-calls plus `fetch_vo2max`'s one, so the
  actual field names can be confirmed the same way `planned_workouts`'s were (Stage 15/17/18)
  once the reporting user pastes the output back.

### Stage 17 — Second live-account fix for planned_workouts: the real `trainingPlanId` key 🔄

The Stage 16 Diagnostics panel immediately paid off: the reporting user ran the `training_plans`
check against their real active plan ("TCS Amsterdam Marathon Plan") and pasted back the actual
JSON — confirming `trainingPlanList` (Stage 15's fix) was right, but also that `_get(plan, "planId",
"id")` matched neither key on a real plan entry, so `plan_id` was always `None` and every plan
was silently skipped. The `training_plan_detail` check's own diagnostic output made this
unambiguous: `{"note": "Could not find a plan id (planId/id) on the first plan entry.", ...}`.

- ✅ **Confirmed and fixed**: a plan entry's own id field is `trainingPlanId` (an integer, e.g.
  `43075722`), not `planId`/`id`. `fetch_planned_workouts` and `fetch_diagnostic`'s
  `training_plan_detail` check both updated to check `trainingPlanId` first, keeping the old
  guesses as lower-priority `_get()` fallbacks. Also confirmed live that this same account's plan
  has `trainingPlanCategory: "FBT_ADAPTIVE"`, verifying Stage 15's adaptive-routing fix is correct
  too — `get_adaptive_training_plan_by_id` is the right endpoint for this account.
- ✅ Verified against the exact real JSON shape pasted by the reporting user (not just a synthetic
  test fixture): `fetch_planned_workouts` now correctly extracts `plan_id="43075722"` and calls
  `get_adaptive_training_plan_by_id(43075722)` (the real integer, not stringified) for this
  account's plan.
- ✅ Raised `_DIAGNOSTIC_OUTPUT_LIMIT` from 8000 to 60000 chars — a live `scheduled_workouts`
  check for one calendar month truncated before reaching the dates that actually mattered
  (`get_scheduled_workouts`'s `calendarItems` list is verbose; each item has ~30 mostly-null
  fields). The `<pre>` box already scrolls internally and the copy button handles large text
  fine, so there was no reason to keep the original conservative cap.
- ✅ **Resolved in Stage 18**: the training-plan detail response's own shape is now confirmed against
  a real `get_adaptive_training_plan_by_id` response (the reporting user's `plan_id` fix from this
  same milestone let the sync reach that endpoint for the first time). See Stage 18.

### Stage 18 — Third live-account fix: the real `taskList`/`taskWorkout` shape, workouts confirmed end-to-end 🔄

With `plan_id` extraction fixed (Stage 17), the reporting user's next sync reached the real
`get_adaptive_training_plan_by_id` response for the first time — and pasted it back complete.
This is the first `planned_workouts` fix in three rounds (Stage 15/Stage 17/Stage 18) confirmed
byte-for-byte against real data end-to-end, not just "no longer 400s."

- ✅ **Confirmed the scheduled-day list key is `taskList`**, not `workouts`/`scheduledWorkouts`/
  `days` as guessed — kept as lower-priority `_get()` fallbacks for an unconfirmed non-adaptive
  (phased) plan shape. Each day entry's date is `calendarDate`, already `YYYY-MM-DD` (one of the
  original guesses happened to be right).
- ✅ **Confirmed workout name/type/duration live nested one level deeper**, under
  `taskWorkout`, not on the day entry itself: `taskWorkout.workoutName` (e.g. `"Threshold"`,
  `"Base"`, `"Anaerobic"` — exact match to the reporting user's Garmin Connect app screenshot),
  `taskWorkout.trainingEffectLabel` (e.g. `"LACTATE_THRESHOLD"`, `"AEROBIC_BASE"`,
  `"ANAEROBIC_CAPACITY"`) mapped to `workout_type`, and `taskWorkout.estimatedDurationInSecs`
  mapped to `planned_duration_seconds` — verified byte-for-byte: `3660`/`3120`/`5100`/`3000`
  seconds matched that account's own app showing `"1:01:00"`/`"52:00"`/`"1:25:00"`/`"50:00"` for
  the same four workouts, respectively.
- ✅ **Confirmed and handled rest days**: a day entry whose `taskWorkout.restDay` is `true` has no
  real workout (`workoutName`/`sportType` are `null`) — skipped rather than stored as an empty
  placeholder row.
- ⬜ **Still open**: no structured pace or heart-rate-zone target field exists anywhere in the
  real response — Garmin represents that as free text in `taskWorkout.workoutDescription`
  instead (e.g. `"2x18:00@162bpm"`, `"137bpm"`, `"7x1:00@Very Hard"`), format varying enough
  (sometimes an `@`-prefixed bpm, sometimes bare, sometimes no numeric value at all for
  effort-based intervals) that parsing wasn't attempted this round.
  `planned_target_pace_sec_per_km`/`planned_target_hr_low`/`planned_target_hr_high` are `None`
  for every workout for now — a possible follow-up once more real examples across different
  workout types confirm a reliable text-parsing pattern. `planned_distance_meters` is `None` too
  — no distance field exists at all for this account's (duration/HR-based) workouts; may differ
  for a distance-based plan.
- ✅ New regression test byte-for-byte reproducing the full real `taskList` response the
  reporting user pasted (7 day-entries: 5 real workouts + 2 rest days), asserting the exact
  durations/names/dates match and rest days are correctly excluded.
- ✅ **Confirmed and fixed a real data-loss bug: `taskList` only ever returns one week**
  (reported live, with the full real response pasted — all 7 entries share one `weekId`, 34).
  Neither `get_training_plan_by_id` nor `get_adaptive_training_plan_by_id` takes a date-range
  argument at all; the sync's `±14`-day `[start_date, end_date]` window was only ever used as a
  post-hoc filter, never something Garmin actually honored. `_replace_planned_workouts` used to
  DELETE the *entire* requested window every sync but only ever re-INSERT the one week Garmin
  actually returned — silently wiping any other week's already-synced rows with nothing to
  replace them. Fixed by having `GarminClient.fetch_planned_workouts`/`_normalize_planned_workouts`
  return the exact set of calendar dates a response actually covers (`covered_dates`, including
  rest-day dates so a day flipping from "workout" to "rest" still clears its stale row) alongside
  the workouts themselves; `_replace_planned_workouts` now scopes its DELETE to exactly that set
  instead of the full requested window. A confirmed-empty `trainingPlanList` (no active plan) is
  treated as a complete answer covering the whole window (correctly clearing stale rows for a
  since-removed plan); a transient fetch failure returns an empty `covered_dates` instead, so a
  network blip can no longer wipe out otherwise-good existing data either — a stricter guarantee
  than the pre-fix behavior had for that case too.

### Stage 19 — Documented, versioned, changelog-tracked release 🔄

- ✅ `DOCS.md` complete: install steps, all config options (now six, since milestone Stage 6 added
  `mcp_auth_token`), MCP connection instructions (`http://homeassistant.local:8765/mcp`), and the
  known-risk note about Garmin auth breakage
- ✅ `README.md` complete: accurate status (Stage 1–Stage 4 implemented, nothing released yet), a
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

### Stage 20 — Web UI redesign: typographic hierarchy, boxed cards, login moved to Settings 🔄

Requested live, with two real device screenshots for reference (the add-on's own Dashboard, and
Garmin Connect's "Personal Records" list): the ingress web UI's typography was effectively
monotone (one weight/size for almost everything) and the stat/activity lists were flat
hairline-bordered lists rather than the boxed-card look the reference screenshot used. A design
mockup was built and shared as an Artifact for review before any code changed, per explicit
request — approved, then implemented.

- ✅ New CSS token set in `_STYLE` (`app/mfa_web/server.py`): kept the existing `--bg`/`--card`/
  `--text`/`--muted`/`--border`/`--ok`/`--error`/`--primary` token *roles* (the color palette
  itself wasn't asked to change), but shifted the neutrals from flat grey to a subtle cool
  blue-grey that harmonizes with the existing blue `--primary`, and added a `--tile`/
  `--border-soft` pair so stat tiles read as a grouped unit without heavy borders. New type scale
  replacing the previous one-weight-everywhere styling: `.eyebrow` (0.7rem, uppercase, letter-
  spaced section labels), `.stat-label` (0.76rem), body copy (0.85rem), `.row-title` (0.92rem),
  `.stat-value`/`.row-value` (0.98–1.7rem, bold, `font-variant-numeric: tabular-nums` so digits
  don't jitter), `h1` (1.375rem).
- ✅ Dashboard's four "Total X synced" lines (previously plain `<p class="stat">` text) became a
  2×2 grid of boxed `.stat-tile`s (label on top, big number below); "Recent activities" became
  individual rounded `.row-card` rows (title+timestamp left, distance right) instead of a
  hairline-bordered `<ul>` — both patterns lifted directly from the Garmin Personal-Records
  reference screenshot. The Running tab's weekly-mileage list got the same `.row-card` treatment
  for visual consistency, even though it wasn't explicitly called out.
- ✅ **Login moved from the Dashboard to the Settings tab**: new `_account_html()` (an "Account"
  card, same login-status message/button copy as before, just relocated) is now prepended to
  `_settings_body()`. The Dashboard no longer shows login status/controls at all — instead, a
  `p.error` notice ("Not connected to Garmin Connect — connect in Settings.") appears only when
  there's no cached session, and "Sync now" only appears once connected (unchanged logic, just
  relocated). `start()`/`verify()`'s error/success pages and their "Back" links now point at
  `settings` (with `active_tab="settings"`) instead of the Dashboard, since that's where the
  login flow now lives; `sync()`'s pages correctly keep pointing at the Dashboard, since that's
  where "Sync now" itself lives.
- ✅ **Real bug caught during manual browser verification, not by the test suite**: `_page()` used
  to wrap every page's entire body in one outer `<div class="card">` — harmless when content was
  flat paragraphs, but once individual `.stat-tile`/`.row-card`/`.card` elements were introduced
  *inside* that same body, everything was doubly-boxed (one big white card containing smaller
  grey-on-white cards, barely distinguishable). Fixed by removing the outer wrapper entirely.
- ✅ **Second real bug caught the same way**: the "not connected" notice was originally a
  `.badge` (the same `display:flex` pill used for the compact "Last sync: …" status), but
  `.badge` has no `flex-wrap` and the notice's text contains an inline `<a>` link — a flex
  container splits text-around-an-element into separate anonymous flex items, and without wrap
  they overlapped/garbled instead of line-wrapping normally. `.badge` is now documented as
  single-text-run-only; the notice uses the existing `p.error` block style instead, which wraps
  arbitrary inline content correctly.
- ✅ Verified with a real headless-browser session (Playwright against a locally-run
  `python3 -m app.mfa_web.server`, seeded with realistic data), not just `TestClient` substring
  assertions: screenshotted Dashboard/Running/Settings in both the connected and
  not-connected-yet states, in both light and dark `prefers-color-scheme` — both bugs above were
  only visible this way, not from the updated test suite (which still passed the whole time).
- ✅ Minor version bump (`0.4.0`, not a patch) — a user-facing redesign + a real information-
  architecture change (login relocated to a different tab), not a bug fix.

### Stage 21 — Fix: CI always fails on `main` right after a post-release PR merges 🔄

Noticed live, with a linked failing run: `main`'s CI (specifically the Lint job's
version-ordering check) turned red on every single push immediately following a merged
post-release PR — not occasionally, every time. Root cause: `release.yml`'s post-release PR
bumps `stridesync/NEXT_VERSION` to the next patch but never touched
`stridesync-dev/config.yaml`, which the check requires to always start with `NEXT_VERSION` — so
the invariant broke the instant the post-release PR merged, and stayed broken until some later
PR happened to bump the dev version by hand (which is exactly what had to be done manually on
almost every PR this session).

- ✅ **Confirmed non-blocking, but real noise, not just a fluke**: the failing run is a plain
  push to `main`, not a PR — `CI Pass` only gates PRs, so nothing was actually blocked. Still,
  worth fixing: it's a red X on every release with nothing to act on, and the "some later PR
  bumps it" step was easy to forget (it wasn't forgotten this session only because it kept
  getting caught by CI on the *next* PR and fixed as a drive-by).
- ✅ `release.yml`'s post-release step now also runs
  `sed -i 's/^version:.*/version: "${NEXT}b1"/' stridesync-dev/config.yaml` alongside the
  existing `stridesync/config.yaml`/`NEXT_VERSION` bumps, in the same commit/PR. `b1` is always
  safe here — `NEXT_VERSION` was just set to a value that could not have existed before, so no
  `v{NEXT}b1` tag can already exist. `stridesync-dev/config.yaml` added to the PR's `git add` and
  its "Changes in this PR" description.
- ✅ Verified by simulating both the `sed` command and CI's exact version-ordering check logic
  locally against copies of the real config files — confirmed the check now exits `0` for the
  post-fix state (`released=0.4.0 < next=0.4.1`, `dev=0.4.1b1` matches `NEXT_VERSION=0.4.1`)
  where it previously failed.
- ✅ `CLAUDE.md` updated: the versioning table, the "Pre-release version must always track
  NEXT_VERSION" section, and the Release workflow's post-release-PR bullet all previously said
  bumping `stridesync-dev/config.yaml` was purely a PR's job — now documented as
  release-workflow-owned-by-default, with a PR only needing to bump it further when shipping a
  *second* pre-release before the next stable release.

### Stage 22 — Fourth live-account fix for planned_workouts: completed days must never be re-deleted 🔄

Reported live, one day after Stage 18's fix shipped, with a second full real
`get_adaptive_training_plan_by_id` response pasted for comparison: Stage 18's `covered_dates`
mechanism correctly stopped deleting *other weeks'* rows, but it was still unconditionally adding
every in-window date — including already-*completed* ones — to `covered_dates`, so a completed
day's row kept getting deleted-and-reinserted on every sync it still happened to appear in, and
worse, once Garmin stopped returning it at all (confirmed live: `2026-07-07`'s "Threshold"
workout, present in the first pasted response, was gone entirely from the second one pasted a day
later) there was no longer even a fresh row to replace the deleted one with.

- ✅ **Confirmed `taskList` is a small rolling window (~7 entries), not a fixed calendar week**:
  the second pasted response has 6 entries on `weekId 34` and a 7th on `weekId 35` — Stage
  18/19's "only ever one week" description is now known to be wrong; corrected throughout
  `garmin_client.py`/`scheduler.py` docstrings.
- ✅ **Confirmed each entry carries `taskWorkout.adaptiveCoachingWorkoutStatus`**, at least
  `"NOT_COMPLETE"` (still pending, safe to treat as covered/refreshable) and
  `"COMPLETED_TODAYS_WORKOUT"` (already done). Per the user's explicit instruction, only
  `"NOT_COMPLETE"` days are now added to `covered_dates`/replaced; a day with any other status is
  skipped entirely — its existing row, if any, is left untouched — and a day whose
  `taskWorkout` has no `adaptiveCoachingWorkoutStatus` field at all falls back to the pre-Stage-22
  "covered" behavior (for the unconfirmed non-adaptive/phased plan shape).
- ✅ New regression test byte-for-byte reproducing the second pasted response (7 entries, 4
  `NOT_COMPLETE` workouts survive, the `COMPLETED_TODAYS_WORKOUT` entry and both rest days are
  excluded from `covered_dates`), plus three focused unit tests covering the completed-workout,
  completed-rest-day, and missing-status-field cases individually.
  Full suite: 270 passed.
- ✅ Verified end-to-end against a real temporary SQLite DB (not just mocks): synced a
  `NOT_COMPLETE` day, then re-synced with that same day now `COMPLETED_TODAYS_WORKOUT` — confirmed
  its row was excluded from the second sync's `covered_dates` and survived completely untouched
  (`synced_at` still pointed at the first sync).

### Stage 23 — `running-coach` example skill: charting conventions for pace/HR over time 🔄

Added, user-provided, following the same "example Skill, purely additive documentation" pattern
as Stage 9's original `docs/skills/running-coach/SKILL.md`: a new "Charting run data (pace / HR
over time)" section giving concrete conventions for visualizing `activity_samples` pace/HR time
series, tuned against real user feedback comparing chart output to the Garmin Connect app.

- ✅ New section covers: pulling `activity_samples` at a high `max_points` (≈200) for Garmin-like
  density; building the x-axis from `elapsed_seconds` in minutes; extending the time axis to the
  activity's true duration via a numeric `x_axis.min`/`max` (not a per-point label array, which
  was found to visibly truncate the last ticks); formatting pace in decimal min/km with the y-axis
  flipped so faster reads higher, matching Garmin; clipping GPS-dropout pace spikes; plotting HR
  in true bpm on a tight range; and rendering pace and HR as two separate stacked charts on a
  shared time axis rather than one scaled single-axis overlay, since the chart tool has no second
  y-axis (a real failure — a scaled HR line pushed off the pace chart — motivated this rule).
  Also documents the chart tool's known limitations (no dual y-axis, no target-pace reference
  line, no area fill) so a coaching response states them honestly rather than pretending Garmin
  parity.
- ✅ Purely additive documentation — no application code changed, entirely optional to use.

### Stage 24 — New MCP tool: `search_activities` (filter by date range, type, distance) 🔄

Requested directly: `recent_activities` only ever returns the most-recent-N activities, with no
way to look up e.g. "my runs over 20km in June" or "cycling activities last week" without pulling
a large `limit` and filtering client-side. Added a dedicated search tool instead.

- ✅ New `find_activities` query function (`app/mcp/server.py`) and `search_activities` MCP tool:
  optional `start_date`/`end_date` (inclusive calendar-date bounds), `activity_type`
  (case-insensitive exact match), `min_distance_meters`/`max_distance_meters`, and `limit`
  (1-200, default 20, same clamp as every other tool) — every filter is optional and combines
  with AND; calling it with no filters behaves exactly like `recent_activities`. Results are
  newest-first, same ordering as `recent_activities`.
- ✅ Unit tests covering each filter individually, combined filters, the no-filter passthrough
  case, and `limit`; full suite green (276 passed, up from 270).
- ✅ Verified end-to-end with a real `fastmcp.Client` call (not just unit tests) against a seeded
  DB with a running activity and a cycling activity — confirmed the type filter, distance filter,
  and date-range filter each returned exactly the expected activity.

### Stage 25 — `running-coach` example skill: race-distance performance comparison via `search_activities` 🔄

Requested directly, as a follow-up to Stage 24's new `search_activities` tool: a new
"Comparing race-distance performance over time" section in `docs/skills/running-coach/SKILL.md`
so the skill can find and compare a runner's history at a specific race distance (10K, half
marathon, marathon) instead of relying on `recent_activities` or memory of past results.

- ✅ New section covers: using `min_distance_meters`/`max_distance_meters` tolerance bands (not
  an exact match, since GPS/course variance means a "10K" is rarely stored as exactly 10000m) for
  each of the three race distances; combining with `activity_type="running"` and a wide/omitted
  `start_date` to search full history; treating results as newest-first with the rest as the
  oldest-to-newest comparison set; and explicitly flagging that a distance-band match isn't
  necessarily a race (a training run can coincidentally land in the same band) — use
  `activity_name`/`training_effect_label` to distinguish, or ask if ambiguous.
- ✅ Comparison guidance: line up pace **and** HR together (pace improving at lower/similar HR is
  real fitness gain; pace improving only because HR rose is a harder effort, not more fitness),
  pull `activity_laps` for pacing-strategy detail on standout runs (a race is one continuous
  effort, so the full km-split set is the meaningful unit — not the work-rep/recovery
  segmentation Step 2 uses for structured sessions), and cross-reference `training_baseline`'s
  race predictions / `vo2max_trend` where available.
- ✅ Purely additive documentation — no application code changed, entirely optional to use.

### Stage 26 — Real training load (CTL/ATL/TSB/ACWR) in `daily_wellness`, sourced from a Garmin-ecosystem review 🔄

Requested directly, after reviewing another open-source Garmin Connect MCP server
(`Taxuspt/garmin_mcp`, built on the same `python-garminconnect` library) for tools/data worth
adding to StrideSync. Its training-load tool reads acute/chronic training load and ACWR from a
nested path in `get_training_status`'s response — the same call `fetch_daily_wellness`
already makes for `training_status_label`, so this is genuine new signal at no extra API cost.

- ✅ **Confirmed (via cross-referencing that project's tested implementation, not yet against a
  live account of this add-on's own)**: `get_training_status`'s `trainingStatusFeedbackPhrase`
  and acute/chronic training load actually live nested under
  `mostRecentTrainingStatus.latestTrainingStatusData.<device id>` (device id is a dynamic,
  per-device key — "take the first value" is the only stable way to read it), not at or near the
  top level as originally guessed. `_normalize_daily_wellness` now tries this nested path first
  for `training_status_label`, falling back to the original top-level guesses only if it's empty
  — existing tests built on the old guess still pass unchanged, since the fallback behavior is
  identical to before.
- ✅ Three new `daily_wellness` columns, all from that same nested device entry's
  `acuteTrainingLoadDTO`: `acute_training_load` (`dailyTrainingLoadAcute`), `chronic_training_load`
  (`dailyTrainingLoadChronic`), `acute_chronic_workload_ratio` (`dailyAcuteChronicWorkloadRatio`,
  Garmin's own value, not computed locally). A fourth, `training_stress_balance`, **is** computed
  locally (`chronic - acute`, the standard CTL−ATL "form" calculation) since Garmin doesn't
  expose it directly.
- ✅ Migration via `_add_column_if_missing` for the three new `daily_wellness` columns (an
  already-shipped table) — new test confirms an older on-disk database gains them without losing
  existing rows.
- ✅ `daily_wellness` MCP tool docstring updated to mention the new fields; `daily_wellness`
  query function's `SELECT` extended to include them.
- ✅ New unit tests (nested-path extraction, nested-path-takes-priority-over-top-level-guess,
  graceful `None` degradation when the nested structure or `acuteTrainingLoadDTO` is absent) plus
  an integration-level `fetch_daily_wellness` test; full suite green (281 passed, up from 276).
- ✅ Verified end-to-end with a real `fastmcp.Client` call against a seeded DB — confirmed all
  four new fields round-trip correctly through the `daily_wellness` tool.
- ⬜ **Still unconfirmed against a live account of this add-on's own** — flagged the same way
  every other best-effort field mapping in this codebase is, pending a live-account check (or a
  future Diagnostics-panel addition) the way `planned_workouts`'/`vo2max_history`'s guesses
  eventually were.

### Stage 27 — Body Battery, stress, and respiration in `daily_wellness`, second follow-up from the Garmin-ecosystem review 🔄

Second of three follow-ups from reviewing `Taxuspt/garmin_mcp` (Stage 26 was the first, shoe/gear
mileage tracking — Stage 28 — is the third). Three more independently-fetched recovery signals,
same field-name confidence level as Stage 26's training-load fix (sourced from that project's
tested implementation, not yet confirmed against a live account of this add-on's own).

- ✅ Three new best-effort sub-fetches added to `fetch_daily_wellness`, each wrapped
  individually like the original five: `get_body_battery(cdate, cdate)` (the one sub-call whose
  underlying method takes a date *range*, not a single date — called with `cdate` as both
  bounds), `get_stress_data(cdate)`, `get_respiration_data(cdate)`.
- ✅ Six new `daily_wellness` columns: `body_battery_charged`/`body_battery_drained` (Body
  Battery's `charged`/`drained` fields — its headline 0-100 *level* is deliberately **not**
  included, since only `charged`/`drained` are confirmed field names; the level appears to live
  in a `bodyBatteryValuesArray` time series whose exact shape isn't confirmed, so it's not
  guessed at), `stress_avg`/`stress_max` (`avgStressLevel`/`maxStressLevel`),
  `respiration_waking_avg`/`respiration_sleep_avg` (`avgWakingRespirationValue`/
  `avgSleepRespirationValue`).
- ✅ `get_body_battery`'s real response is a *list* of per-day entries (like `get_max_metrics` —
  see `_normalize_vo2max`'s docstring) — a new shared `_first_dict()` helper unwraps that the
  same way, reused for future list-shaped responses too.
- ✅ Migration via `_add_column_if_missing` for all six new `daily_wellness` columns (an
  already-shipped table) — new test confirms an older on-disk database gains them without losing
  existing rows.
- ✅ `daily_wellness` MCP tool docstring updated; `daily_wellness` query function's `SELECT`
  extended to include the six new fields.
- ✅ New unit tests (merges all three new sources, defaults to `None` when the new args aren't
  passed at all — confirms they're genuinely optional so older call sites keep working, empty-list
  and non-dict-list-element degradation for `get_body_battery`) plus an integration-level
  `fetch_daily_wellness` test and an "everything fails" test extended to cover the three new
  endpoints; full suite green (287 passed, up from 281).
- ✅ Verified end-to-end with a real `fastmcp.Client` call against a seeded DB — confirmed all six
  new fields round-trip correctly through the `daily_wellness` tool.
- ⬜ **Still unconfirmed against a live account of this add-on's own** — same caveat as Stage 26.

---

## Getting Started (Development)

### Prerequisites

- Python 3.12+
- Docker

### Build & run the add-on standalone

See **Local Development & Testing** in `CLAUDE.md` for the full standalone `docker build` /
`docker run` walkthrough — you do not need a Home Assistant instance until milestone Stage 4.

### Manual sync (Stage 1+)

```bash
cd stridesync
pip install -r app/requirements.txt
python3 -m app.sync.scheduler --once   # one-shot sync, doesn't wait for the interval
```

### HA Add-on Installation (once published, Stage 4+)

1. Settings → Add-ons → Add-on Store → ⋮ → Repositories
2. Add: `https://github.com/nsaputro/stride-sync`
3. Find **StrideSync** → Install → Configure Garmin credentials → Start

---

_Own your training data — talk to it 🏃_
