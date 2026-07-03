# Single interface to Garmin Connect auth + activity fetch. sync and mcp code should never call
# garmy (or the python-garminconnect fallback) directly — see CLAUDE.md, Coding Conventions.
#
# TODO (v0.1): authenticate via garmy, fetch recent activities.
