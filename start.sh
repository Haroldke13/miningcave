#!/usr/bin/env bash
set -euo pipefail

# Render web services provide PORT. If APP_MODE is not set explicitly,
# default to chat mode when PORT exists so HTTP binding always happens.
if [[ -n "${APP_MODE:-}" ]]; then
  MODE="${APP_MODE}"
elif [[ -n "${PORT:-}" ]]; then
  MODE="chat"
else
  MODE="worker"
fi

if [[ "$MODE" == "chat" ]]; then
  exec gunicorn \
    --bind "0.0.0.0:${PORT:-10000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --threads 4 \
    --timeout 120 \
    customer_agent_app:app
fi

if [[ "$MODE" == "pilot_once" ]]; then
  exec python3 -m automation.pilot_mode
fi

exec python3 inventory_worker.py --daily --run-pilot-mode
