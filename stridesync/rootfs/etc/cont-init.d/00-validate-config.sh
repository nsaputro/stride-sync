#!/usr/bin/with-contenv bashio
# Runs once before sync-scheduler and mcp-server start. Fails loudly (per PROJECT_PLAN.md's
# "known risk" section) rather than letting either service start against missing/bad config.
#
# Uses plain `bashio::config` + a shell emptiness check rather than `bashio::config.has_value`:
# .has_value calls out to the Supervisor API, which doesn't exist when running standalone
# (`docker run`, no real HA Supervisor) — it silently reports every value missing
# ("curl: Could not resolve host: supervisor"), so this cont-init script would kill the
# container even with valid options.json. Plain `bashio::config` reads /data/options.json
# directly and works in both standalone and real-Supervisor contexts (same pattern the
# sync-scheduler/mcp-server run scripts already use).

bashio::log.info "Validating StrideSync configuration..."

GARMIN_USERNAME=$(bashio::config 'garmin_username')
GARMIN_PASSWORD=$(bashio::config 'garmin_password')

if [ -z "${GARMIN_USERNAME}" ] || [ -z "${GARMIN_PASSWORD}" ]; then
    bashio::exit.nok "garmin_username and garmin_password must be set in the add-on configuration."
fi
