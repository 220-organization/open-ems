#!/usr/bin/env bash
# Debug Deye Smart Load for inverter 2602114844 (Power flow UI: market=oree, zone=ES).
# API: http://127.0.0.1:9221  |  UI: http://localhost:9220/?market=oree&zone=ES&inverter=deye%3A2602114844&exportMetric=monthly_rates
#
# NOTE: OPTIONS /api/deye/smart-load is CORS preflight only — it does NOT change the inverter.
# POST /api/deye/smart-load saves DB pref; Deye writes happen on scheduler tick (every 5 min) or via gen-port below.
#
# Set PIN before run (from plant/device label suffix in Deye Cloud):
#   export DEYE_DEBUG_PIN='1234'

set -euo pipefail
cd "$(dirname "$0")/.."

API_BASE='http://127.0.0.1:9221'
DEVICE_SN='2602114844'
PIN="${DEYE_DEBUG_PIN:-REPLACE_WITH_PIN}"

echo "=== 1) GET smart-load pref + gen state (Open EMS) ==="
curl -sS -X GET \
  "${API_BASE}/api/deye/smart-load?deviceSn=${DEVICE_SN}" \
  -H 'Accept: application/json' | jq .

echo
echo "=== 2) POST smart-load — enable automation pref in DB only (needs PIN) ==="
curl -sS -X POST \
  "${API_BASE}/api/deye/smart-load" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -d "{\"deviceSn\":\"${DEVICE_SN}\",\"enabled\":true,\"pin\":\"${PIN}\"}" | jq .

echo
echo "=== 3) POST smart-load/gen-port — write Deye Gen port OFF (On Grid always on = false) ==="
curl -sS -X POST \
  "${API_BASE}/api/deye/smart-load/gen-port" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -d "{\"deviceSn\":\"${DEVICE_SN}\",\"enabled\":false,\"pin\":\"${PIN}\"}" | jq .

echo
echo "=== 4) POST smart-load/gen-port — write Deye Gen port ON (On Grid always on = true) ==="
curl -sS -X POST \
  "${API_BASE}/api/deye/smart-load/gen-port" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -d "{\"deviceSn\":\"${DEVICE_SN}\",\"enabled\":true,\"pin\":\"${PIN}\"}" | jq .

echo
echo "=== 5) GET ess-power — live PV / load / grid (scheduler uses these) ==="
curl -sS -X GET \
  "${API_BASE}/api/deye/ess-power?deviceSn=${DEVICE_SN}" \
  -H 'Accept: application/json' | jq '{deviceSn, pvW, loadW, gridW, socPercent, source}'

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -n "${DEYE_APP_ID:-}" && -n "${DEYE_APP_SECRET:-}" && -n "${DEYE_EMAIL:-}" && -n "${DEYE_PASSWORD:-}" ]]; then
  DEYE_BASE="${DEYE_API_BASE_URL:-https://eu1-developer.deyecloud.com/v1.0}"
  DEYE_BASE="${DEYE_BASE%/}"
  if command -v shasum >/dev/null 2>&1; then
    PASS_HASH=$(printf '%s' "${DEYE_PASSWORD}" | shasum -a 256 | awk '{print $1}')
  else
    PASS_HASH=$(printf '%s' "${DEYE_PASSWORD}" | sha256sum | awk '{print $1}')
  fi

  echo
  echo "=== 6) Deye Cloud token (.env) ==="
  TOKEN_JSON=$(curl -sS -X POST \
    "${DEYE_BASE}/account/token?appId=${DEYE_APP_ID}" \
    -H 'Content-Type: application/json' \
    -d "{\"appSecret\":\"${DEYE_APP_SECRET}\",\"email\":\"${DEYE_EMAIL}\",\"companyId\":${DEYE_COMPANY_ID:-0},\"password\":\"${PASS_HASH}\"}")
  echo "${TOKEN_JSON}" | jq '{success, msg, accessToken: (.accessToken // .data.accessToken // null) | if . then (.[0:20] + "...") else null end}'
  TOKEN=$(echo "${TOKEN_JSON}" | jq -r '.accessToken // .data.accessToken // empty')
  if [[ -z "${TOKEN}" ]]; then
    echo "Token failed — check DEYE_* in .env" >&2
    exit 1
  fi

  echo
  echo "=== 7) Deye SmartLoad READ (try paths) ==="
  for PATH_SUFFIX in \
    '/order/sys/smartLoad/read' \
    '/config/smartLoad/read' \
    '/order/smartLoad/read'; do
    echo "--- POST ${DEYE_BASE}${PATH_SUFFIX} ---"
    curl -sS -X POST \
      "${DEYE_BASE}${PATH_SUFFIX}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H 'Content-Type: application/json' \
      -d "{\"deviceSn\":\"${DEVICE_SN}\"}" | jq .
  done

  echo
  echo "=== 8) Deye device/latest — SMART_LOAD_POWER / Gen port registers ==="
  curl -sS -X POST \
    "${DEYE_BASE}/device/latest" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "{\"deviceList\":[\"${DEVICE_SN}\"]}" \
    | jq '.deviceDataList[0].dataList[]? | select(.key | test("SMART|LOAD|GEN|PV|PPV|TotalDC"; "i"))'
else
  echo
  echo "=== 6–8) Skipped direct Deye curls — set DEYE_APP_ID, DEYE_APP_SECRET, DEYE_EMAIL, DEYE_PASSWORD in open-ems/.env ==="
fi

echo
echo "Done. Watch API logs for: Deye smart-load: using endpoint / set onGridAlwaysOn="
