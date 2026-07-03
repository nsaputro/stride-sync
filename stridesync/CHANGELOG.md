# Changelog

All notable changes to the StrideSync add-on are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions match `config.yaml` and the GitHub release tags.

---

## [Unreleased]

### Added
- Garmin Connect sync client, SQLite schema, and a manual sync CLI
  (`python3 -m app.sync.scheduler --once`) for verifying auth and the data model against a real
  Garmin account. Not yet wired into a continuous s6 service — see PROJECT_PLAN.md milestone
  v0.2.
