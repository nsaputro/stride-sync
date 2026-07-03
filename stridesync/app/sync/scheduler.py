# Sync scheduler entry point — python3 -m app.sync.scheduler
# Runs as the sync-scheduler s6 service (rootfs/etc/services.d/sync-scheduler/run).
# See PROJECT_PLAN.md §1 (Scheduled sync service) and milestones v0.1/v0.2.
#
# TODO (v0.1): --once flag for a single manual sync run (CLI verification, no scheduling loop).
# TODO (v0.2): loop on sync_interval_hours, write outcomes to sync_log, fail loud on auth errors.
