#!/usr/bin/with-contenv bashio
# Runs once before sync-scheduler and mcp-server start. Fails loudly (per PROJECT_PLAN.md's
# "known risk" section) rather than letting either service start against missing/bad config.

bashio::log.info "Validating StrideSync configuration..."

if ! bashio::config.has_value 'garmin_username' || ! bashio::config.has_value 'garmin_password'; then
    bashio::exit.nok "garmin_username and garmin_password must be set in the add-on configuration."
fi
