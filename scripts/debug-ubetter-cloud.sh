#!/usr/bin/env bash
# Debug Ubetter EMS cloud (Open API v1): auth token + device list + summary/detail.
#
# Usage:
#   ./scripts/debug-ubetter-cloud.sh              # default SN prefix UBT042 (prod 241kWh)
#   ./scripts/debug-ubetter-cloud.sh UBT0420215200730007
#
# Requires UBETTER_PASSWORD in open-ems/.env (or exported). Optional overrides:
#   UBETTER_BASE_URL, UBETTER_USERNAME, UBETTER_TENANT_USERNAME
#
# Docs: docs/postman/ubetter-api.postman_collection.json
# Swagger: https://eur.ubetter.com.cn/ems-open-api/swagger-ui/index.html

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

BASE_URL="${UBETTER_BASE_URL:-https://eur.ubetter.com.cn/ems-open-api}"
BASE_URL="${BASE_URL%/}"
USERNAME="${UBETTER_USERNAME:-220km}"
TENANT_USERNAME="${UBETTER_TENANT_USERNAME:-220km}"
DEVICE_FILTER="${1:-UBT042}"

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required (brew install jq / apt install jq)" >&2
  exit 1
fi

if [[ -z "${UBETTER_PASSWORD:-}" ]]; then
  echo "ERROR: UBETTER_PASSWORD is not set. Add it to open-ems/.env or export it." >&2
  exit 1
fi

ubetter_curl() {
  local method="$1"
  local path="$2"
  shift 2
  curl -sS -X "${method}" \
    "${BASE_URL}${path}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "X-Tenant-Id: ${TENANT_ID}" \
    "$@"
}

print_api_meta() {
  local label="$1"
  local json="$2"
  local code message
  code=$(echo "${json}" | jq -r '.code // empty')
  message=$(echo "${json}" | jq -r '.message // empty')
  echo "${label}: code=${code:-?} message=${message:-—}" >&2
}

resolve_device_sn() {
  local filter="$1"
  local list_json exact partial

  list_json=$(ubetter_curl GET "/v1/devices?page=1&size=50&onlineStatus=all&productType=all")
  print_api_meta "Device list" "${list_json}"

  exact=$(echo "${list_json}" | jq -r --arg sn "${filter}" '
    .data.items[]? | select(.sn == $sn) | .sn' | head -1)
  if [[ -n "${exact}" ]]; then
    echo "${exact}"
    return 0
  fi

  partial=$(echo "${list_json}" | jq -r --arg p "${filter}" '
    .data.items[]? | select(.sn | test($p; "i")) | .sn' | head -1)
  if [[ -n "${partial}" ]]; then
    echo "${partial}"
    return 0
  fi

  echo "ERROR: no device matches filter '${filter}'. Available SNs:" >&2
  echo "${list_json}" | jq -r '.data.items[]? | "  - \(.sn)  \(.name // "")  online=\(.online // false)"' >&2
  return 1
}

echo "=== Ubetter cloud debug ==="
echo "baseUrl=${BASE_URL}"
echo "username=${USERNAME} tenantUsername=${TENANT_USERNAME}"
echo "deviceFilter=${DEVICE_FILTER}"
echo

echo "=== 1) POST /v1/auth/token ==="
AUTH_JSON=$(curl -sS -X POST "${BASE_URL}/v1/auth/token" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc \
    --arg u "${USERNAME}" \
    --arg p "${UBETTER_PASSWORD}" \
    --arg t "${TENANT_USERNAME}" \
    '{username: $u, password: $p, tenantUsername: $t}')")
print_api_meta "Auth" "${AUTH_JSON}"
echo "${AUTH_JSON}" | jq '{
  code,
  message,
  requestId,
  timestamp,
  data: (.data | if . then {
    tenantId,
    expiresIn,
    accessTokenPreview: (.accessToken | if . then (.[0:24] + "...") else null end)
  } else null end)
}'

AUTH_CODE=$(echo "${AUTH_JSON}" | jq -r '.code // empty')
if [[ "${AUTH_CODE}" != "0" ]]; then
  echo "Auth failed — check UBETTER_PASSWORD and Open API access (IP whitelist, etc.)" >&2
  exit 1
fi

ACCESS_TOKEN=$(echo "${AUTH_JSON}" | jq -r '.data.accessToken // empty')
TENANT_ID=$(echo "${AUTH_JSON}" | jq -r '.data.tenantId // empty')
if [[ -z "${ACCESS_TOKEN}" || -z "${TENANT_ID}" ]]; then
  echo "Auth response missing accessToken or tenantId" >&2
  exit 1
fi

echo
echo "=== 2) Resolve device SN (filter: ${DEVICE_FILTER}) ==="
DEVICE_SN=$(resolve_device_sn "${DEVICE_FILTER}")
echo "Using deviceSn=${DEVICE_SN}"

echo
echo "=== 3) GET /v1/devices/${DEVICE_SN} — realtime summary ==="
SUMMARY_JSON=$(ubetter_curl GET "/v1/devices/${DEVICE_SN}")
print_api_meta "Summary" "${SUMMARY_JSON}"
echo "${SUMMARY_JSON}" | jq '{
  code,
  message,
  data: (.data | if . then {
    sn,
    soc,
    soh,
    batteryPower,
    pvTotalPower,
    gridActivePower,
    loadActivePower,
    batteryVoltage,
    batteryCurrent,
    batteryTemperature,
    reportTime
  } else null end)
}'

echo
echo "=== 4) GET /v1/devices/${DEVICE_SN}/detail?viewScope=group ==="
DETAIL_JSON=$(ubetter_curl GET "/v1/devices/${DEVICE_SN}/detail?viewScope=group")
print_api_meta "Detail" "${DETAIL_JSON}"
echo "${DETAIL_JSON}" | jq '{
  code,
  message,
  data: (.data | if . then {
    viewScopeResolved,
    groupSummary: (.groupRow.summary // null | if . then {
      soc,
      soh,
      capacity,
      online,
      realtimePower: .realtimePower,
      energyFlow: .energyFlow
    } else null end),
    singleSummary: (.singleDevice.summary // null | if . then {soc, soh, online} else null end)
  } else null end)
}'

echo
echo "=== 5) GET /v1/devices/${DEVICE_SN}/run-strategy ==="
STRATEGY_JSON=$(ubetter_curl GET "/v1/devices/${DEVICE_SN}/run-strategy")
print_api_meta "Run strategy" "${STRATEGY_JSON}"
echo "${STRATEGY_JSON}" | jq '{code, message, data}'

echo
echo "=== 6) Optional — local Open EMS proxy (127.0.0.1:9221) ==="
API_BASE="${OPEN_EMS_API_BASE:-http://127.0.0.1:9221}"
if curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 2 "${API_BASE}/docs" | grep -qE '^[23]'; then
  echo "--- GET ${API_BASE}/api/ubetter/device-summary?sn=${DEVICE_SN} ---"
  curl -sS "${API_BASE}/api/ubetter/device-summary?sn=${DEVICE_SN}" | jq '{
    ok,
    configured,
    sn,
    socPercent,
    batteryPowerW,
    pvPowerW,
    gridPowerW,
    loadPowerW,
    reason,
    detail
  }'
else
  echo "Local API not reachable at ${API_BASE} — start ./run-local.sh or set OPEN_EMS_API_BASE"
fi

echo
echo "Done."
