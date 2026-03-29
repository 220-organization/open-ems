#!/bin/sh
set -e
if [ "${RUN_FLYWAY_ON_START}" = "true" ]; then
  python /app/scripts/render_flyway_migrate.py
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8090}"
