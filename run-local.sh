#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Local API against Docker PostgreSQL + Flyway migrations (see README / docker-compose.yml).
# WSL/Ubuntu/macOS: requires Docker Compose v2.
#
# Fixed dev layout: CRA (Power flow UI) on 9220, FastAPI on 9221. Re-run kills listeners first.
# Override: UI_PORT=9330 API_PORT=9331 ./run-local.sh
#
# Fresh DB (drops Postgres volume, re-runs Flyway): ./run-local.sh -clean

CLEAN_DB=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -clean|--clean)
      CLEAN_DB=1
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Usage: ./run-local.sh [options]

  -clean, --clean   Stop compose services and remove the PostgreSQL volume (empty DB, Flyway from scratch).
                    Use after migration checksum conflicts or to reset local data.

  -h, --help        Show this help.

Environment: UI_PORT, API_PORT, DATABASE_URL, UVICORN_RELOAD, REACT_APP_API_BASE_URL, ...

  OPENEMS_OPEN_SWAGGER=0 (default) — set to 1 to also open API Swagger /docs in the default browser after startup.
  The UI does not auto-open a browser; the URL is printed when CRA is ready.

  ROI dev seed: after Flyway migrations runs ./scripts/seed_roi_dev_data.sh for DEVICE_SN=2512291445
  (3 months of PV samples + DAM rows + deye_roi_capex, period start 3 months ago). Change DEVICE_SN in this script if needed.
  Optional: ZONE_EIC (default 10Y1001C--000182). Requires psql or Docker db container.

  Lost-solar test seed: upserts 5-min SoC 100% + PV for Kyiv hours 12–16 (five hours) today (same DEVICE_SN), non-fatal if it fails.

  Power-flow demo seed: POWER_FLOW_DEMO_SN (default 2410102121) — export samples + peak DAM + manual discharge
  rows for landing totals (http://localhost:9220/?inverter=<SN>); non-fatal if it fails.

  When POWER_FLOW_DEMO_SN differs from DEVICE_SN, ROI stack seed (./scripts/seed_roi_dev_data.sh) also runs for
  POWER_FLOW_DEMO_SN (3 months PV/load samples + deye_roi_capex + DAM rows) before the power-flow demo overlay.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1 (use -h for help)" >&2
      exit 1
      ;;
  esac
done

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://openems:openems@127.0.0.1:5433/openems}"

# ROI dev DB seed target (scripts/seed_roi_dev_data.sh)
export DEVICE_SN="2512291445"

# Landing totals demo: peak DAM + manual discharge counters (scripts/seed_power_flow_demo_sn.sql)
POWER_FLOW_DEMO_SN="${POWER_FLOW_DEMO_SN:-2410102121}"

UI_PORT="${UI_PORT:-9220}"
API_PORT="${API_PORT:-9221}"
export PORT="${API_PORT}"

OPENEMS_OPEN_SWAGGER="${OPENEMS_OPEN_SWAGGER:-0}"

# API process does not serve legacy / built HTML; UI is only from the CRA dev server.
export OPEN_EMS_SERVE_SPA=0

_kill_listeners_on_tcp_port() {
  local p="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  lsof -ti "tcp:${p}" | xargs kill -9 2>/dev/null || true
}

echo "Stopping existing processes on Open EMS dev ports (UI ${UI_PORT}, API ${API_PORT}, legacy 3090)…" >&2
_kill_listeners_on_tcp_port "${UI_PORT}"
_kill_listeners_on_tcp_port "${API_PORT}"
_kill_listeners_on_tcp_port "3090"
sleep 1

if ! command -v lsof >/dev/null 2>&1; then
  echo "Note: lsof not found — install it to auto-free ports when re-running this script." >&2
fi

if [[ "${CLEAN_DB}" -eq 1 ]]; then
  echo "Cleaning local database: docker compose down -v (removes volume open_ems_pgdata)…" >&2
  docker compose down -v
fi

docker compose up -d db

echo "Waiting for PostgreSQL..."
for _ in $(seq 1 90); do
  if docker compose exec -T db pg_isready -U openems -d openems >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! docker compose exec -T db pg_isready -U openems -d openems >/dev/null 2>&1; then
  echo "PostgreSQL did not become ready in time." >&2
  exit 1
fi

docker compose run --rm migrate

echo "Running ROI dev DB seed for DEVICE_SN=${DEVICE_SN} (./scripts/seed_roi_dev_data.sh)…" >&2
if ! ./scripts/seed_roi_dev_data.sh; then
  echo "WARN: ROI dev seed failed (non-fatal). Fix DATABASE_URL or run ./scripts/seed_roi_dev_data.sh manually." >&2
fi

echo "Seeding lost-solar SoC test rows (Kyiv today, hours 12–16, five hours) for DEVICE_SN=${DEVICE_SN}…" >&2
if ! docker compose exec -T db psql -U openems -d openems -v "device_sn=${DEVICE_SN}" -f - <<'EOSQL'
\set ON_ERROR_STOP on
INSERT INTO deye_soc_sample (
    device_sn,
    bucket_start,
    soc_percent,
    grid_power_w,
    load_power_w,
    pv_power_w,
    pv_generation_w,
    battery_power_w
)
SELECT
    :'device_sn'::varchar(64),
    g,
    100.0,
    0.0,
    500.0,
    2500.0,
    2500.0,
    0.0
FROM generate_series(
    (((timezone('Europe/Kiev', now()))::date + interval '12 hours')::timestamp AT TIME ZONE 'Europe/Kiev'),
    (((timezone('Europe/Kiev', now()))::date + interval '17 hours')::timestamp AT TIME ZONE 'Europe/Kiev')
        - interval '5 minutes',
    interval '5 minutes'
) AS g
ON CONFLICT (device_sn, bucket_start) DO UPDATE SET
    soc_percent = EXCLUDED.soc_percent,
    grid_power_w = EXCLUDED.grid_power_w,
    load_power_w = EXCLUDED.load_power_w,
    pv_power_w = EXCLUDED.pv_power_w,
    pv_generation_w = EXCLUDED.pv_generation_w,
    battery_power_w = EXCLUDED.battery_power_w;
EOSQL
then
  echo "WARN: Lost-solar SoC seed failed (non-fatal)." >&2
fi

if [[ "${POWER_FLOW_DEMO_SN}" != "${DEVICE_SN}" ]]; then
  echo "Running ROI dev DB seed for POWER_FLOW_DEMO_SN=${POWER_FLOW_DEMO_SN} (./scripts/seed_roi_dev_data.sh)…" >&2
  if ! DEVICE_SN="${POWER_FLOW_DEMO_SN}" ./scripts/seed_roi_dev_data.sh; then
    echo "WARN: ROI dev seed for POWER_FLOW_DEMO_SN failed (non-fatal). Run: DEVICE_SN=${POWER_FLOW_DEMO_SN} ./scripts/seed_roi_dev_data.sh" >&2
  fi
fi

echo "Seeding power-flow demo (export samples + peak + manual discharge) for POWER_FLOW_DEMO_SN=${POWER_FLOW_DEMO_SN}…" >&2
if [[ -f ./scripts/seed_power_flow_demo_sn.sql ]]; then
  if ! docker compose exec -T db psql -U openems -d openems -v "demo_sn=${POWER_FLOW_DEMO_SN}" < ./scripts/seed_power_flow_demo_sn.sql; then
    echo "WARN: Power-flow demo seed failed (non-fatal). Run manually: docker compose exec -T db psql -U openems -d openems -v demo_sn=${POWER_FLOW_DEMO_SN} < ./scripts/seed_power_flow_demo_sn.sql" >&2
  fi
else
  echo "WARN: scripts/seed_power_flow_demo_sn.sql missing — skip power-flow demo seed." >&2
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
pip install -q -r requirements.txt

_open_swagger_ui() {
  local url="http://127.0.0.1:${API_PORT}/docs"
  if [[ -n "${BROWSER:-}" ]]; then
    "$BROWSER" "$url" 2>/dev/null && return
  fi
  case "$(uname -s)" in
    Darwin)
      open "$url"
      ;;
    Linux)
      if grep -qi microsoft /proc/version 2>/dev/null; then
        cmd.exe /c start "" "$url" 2>/dev/null || explorer.exe "$url" 2>/dev/null || true
      elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 &
      elif command -v wslview >/dev/null 2>&1; then
        wslview "$url" 2>/dev/null || true
      else
        echo "Swagger UI: $url" >&2
      fi
      ;;
    *)
      echo "Swagger UI: $url" >&2
      ;;
  esac
}

# CRA dev server — wait until it answers before printing the UI URL.
_wait_for_ui() {
  local url="http://127.0.0.1:${UI_PORT}/"
  local i
  if ! command -v curl >/dev/null 2>&1; then
    echo "Note: curl not found — sleeping 8s before opening UI URL…" >&2
    sleep 8
    return 0
  fi
  for i in $(seq 1 240); do
    if curl -sf --connect-timeout 1 --max-time 3 "$url" >/dev/null; then
      return 0
    fi
    sleep 0.5
  done
  echo "Timed out waiting for UI at $url — open it manually if npm start is still compiling." >&2
  return 1
}

_wait_for_openapi() {
  local url="http://127.0.0.1:${API_PORT}/openapi.json"
  local i
  for i in $(seq 1 150); do
    if command -v curl >/dev/null 2>&1 && curl -sf --connect-timeout 1 --max-time 2 "$url" >/dev/null; then
      return 0
    fi
    if ! command -v curl >/dev/null 2>&1; then
      sleep 2
      return 0
    fi
    sleep 0.2
  done
  echo "Timed out waiting for $url — open /docs manually if the app is up." >&2
  return 1
}

UVICORN_RELOAD="${UVICORN_RELOAD:-1}"
RELOAD_ARGS=()
if [[ "${UVICORN_RELOAD}" != "0" ]]; then
  RELOAD_ARGS=(--reload --reload-dir "${PWD}/app")
  echo "FastAPI: autoreload on (uvicorn --reload, dir app/). Disable with UVICORN_RELOAD=0" >&2
else
  echo "FastAPI: autoreload off (UVICORN_RELOAD=0)" >&2
fi

_cleanup_local_procs() {
  [[ -n "${UVICORN_PID:-}" ]] && kill -TERM "${UVICORN_PID}" 2>/dev/null || true
  [[ -n "${UI_PID:-}" ]] && kill -TERM "${UI_PID}" 2>/dev/null || true
}
trap '_cleanup_local_procs' INT TERM EXIT

echo "Starting API at http://127.0.0.1:${API_PORT} (Swagger at /docs)" >&2
echo "Starting React dev (Fast Refresh) at http://127.0.0.1:${UI_PORT} → API http://127.0.0.1:${API_PORT}" >&2
# Line-buffered Python stdout/stderr so API logs appear immediately in this terminal (Python 3.9-safe).
export PYTHONUNBUFFERED=1
uvicorn app.main:app "${RELOAD_ARGS[@]}" --host 0.0.0.0 --port "${API_PORT}" --log-level info &
UVICORN_PID=$!

if [[ ! -d ui/node_modules ]]; then
  echo "Installing UI dependencies (ui/)…" >&2
  (cd ui && npm install)
fi
(
  cd ui
  export REACT_APP_API_BASE_URL="${REACT_APP_API_BASE_URL:-http://127.0.0.1:${API_PORT}}"
  export PORT="${UI_PORT}"
  export FAST_REFRESH=true
  if grep -qi microsoft /proc/version 2>/dev/null; then
    export CHOKIDAR_USEPOLLING=true
    export WATCHPACK_POLLING=true
  fi
  exec npm start
) &
UI_PID=$!

_wait_for_openapi || true

echo "Waiting for CRA dev server on port ${UI_PORT}…" >&2
_wait_for_ui || true
echo "Open EMS UI: http://127.0.0.1:${UI_PORT}/" >&2

if [[ "${OPENEMS_OPEN_SWAGGER}" == "1" ]]; then
  echo "Opening Swagger UI in the default browser…" >&2
  _open_swagger_ui || true
fi

wait "${UVICORN_PID}"
