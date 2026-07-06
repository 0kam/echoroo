#!/bin/sh
# Restart echoroo celery containers if any of them is not running.
#
# The celery containers fail silently: the backend keeps accepting uploads
# and enqueuing tasks, the frontend polls forever, and nothing surfaces an
# error (this is exactly what happened 2026-06-21..07-04 after a host
# reboot). `restart: unless-stopped` covers daemon/host restarts and
# crashes, but not a manual `docker stop` / `compose stop` that was never
# followed by an `up`. This watchdog closes that gap.
#
# Deliberately NOT a celery-ping healthcheck: the workers run --pool=solo,
# so a worker busy with a long CPU inference task cannot answer pings and
# would be killed mid-task by any ping-based autoheal.
#
# Install (cron, every 5 min):
#   */5 * * * * flock -n /tmp/echoroo-worker-watchdog.lock /path/to/worker-watchdog.sh >> ~/.local/state/echoroo-watchdog.log 2>&1

set -u

# Default: compose.dev.yaml at the repo root (one level above scripts/).
# Override with ECHOROO_COMPOSE_FILE for non-standard layouts.
COMPOSE_FILE="${ECHOROO_COMPOSE_FILE:-$(cd "$(dirname "$0")/.." && pwd)/compose.dev.yaml}"

for name in echoroo-worker-1 echoroo-worker-cpu-1 echoroo-beat-1; do
    running=$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || echo "missing")
    if [ "$running" != "true" ]; then
        echo "$(date -Is) ${name} not running (state=${running}) - starting workers"
        docker compose -f "$COMPOSE_FILE" up -d --no-recreate worker worker-cpu beat
        exit $?
    fi
done
