#!/usr/bin/env bash
# Seed local PostgreSQL with 3 months of deye_soc_sample PV rows + DAM prices + deye_roi_capex (start 3 months ago).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SQL="${ROOT}/db/seed/dev_roi_stack.sql"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: Set DATABASE_URL (e.g. postgresql://user:pass@localhost:5432/open_ems)" >&2
  exit 1
fi

# psql expects postgresql:// — strip SQLAlchemy async driver (same URL as FastAPI uses).
if [[ "${DATABASE_URL}" == postgresql+asyncpg://* ]]; then
  DATABASE_URL="postgresql://${DATABASE_URL#postgresql+asyncpg://}"
fi

if [[ -z "${DEVICE_SN:-}" ]]; then
  echo "ERROR: Set DEVICE_SN to your inverter serial (same as in the Power Flow inverter dropdown)." >&2
  exit 1
fi

ZONE_EIC="${ZONE_EIC:-10Y1001C--000182}"

echo "Seeding ROI dev data for device_sn=${DEVICE_SN} zone_eic=${ZONE_EIC}"

_run_psql() {
  psql "${DATABASE_URL}" \
    -v "device_sn=${DEVICE_SN}" \
    -v "zone_eic=${ZONE_EIC}" \
    -f "${SQL}"
}

if command -v psql >/dev/null 2>&1; then
  _run_psql
elif command -v docker >/dev/null 2>&1 && [[ -f "${ROOT}/docker-compose.yml" ]]; then
  echo "Using docker compose exec db psql (install postgresql-client to use host psql instead)…" >&2
  (
    cd "${ROOT}"
    docker compose exec -T db psql -U openems -d openems \
      -v "device_sn=${DEVICE_SN}" \
      -v "zone_eic=${ZONE_EIC}" \
      -f - < "${SQL}"
  )
else
  echo "ERROR: Need psql on PATH, or Docker with open-ems/docker-compose.yml for db exec." >&2
  exit 1
fi

echo "Done. Reload the app; ROI stack should show PV kWh, DAM UAH sum, and ROI after stats refresh (~3 month window)."
