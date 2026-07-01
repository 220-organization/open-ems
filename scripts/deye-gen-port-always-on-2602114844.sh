#!/usr/bin/env bash
# Direct Deye Cloud: Gen port "On Grid always on" for SN 2602114844.
# Open EMS uses Modbus register 0x00B2 bit 6 via POST /order/customControl (hex payload).
# JSON smartLoadSetup echoes the request (analysisResult 0500) without applying on the device.
#
# Hardcoded copy-paste (set TOKEN from step 1, ORDER_ID from step 2):
#
#   curl -sS -X POST 'https://eu1-developer.deyecloud.com/v1.0/order/customControl' \
#     -H 'Content-Type: application/json' \
#     -H 'Authorization: Bearer TOKEN' \
#     -d '{"deviceSn":"2602114844","content":"{\"cmd\":\"smartLoadSetup\",\"onGridAlwaysOn\":true}"}' | jq .
#
#   curl -sS -X GET 'https://eu1-developer.deyecloud.com/v1.0/order/ORDER_ID' \
#     -H 'Authorization: Bearer TOKEN' | jq .
#
# Open EMS proxy (needs correct plant PIN, not Deye password):
#   curl -sS -X POST 'http://127.0.0.1:9221/api/deye/smart-load/gen-port' \
#     -H 'Content-Type: application/json' \
#     -d '{"deviceSn":"2602114844","enabled":true,"pin":"1234"}' | jq .

set -euo pipefail
cd "$(dirname "$0")/.."

DEYE_BASE='https://eu1-developer.deyecloud.com/v1.0'
DEVICE_SN='2602114844'

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
DEYE_BASE="${DEYE_API_BASE_URL:-$DEYE_BASE}"
DEYE_BASE="${DEYE_BASE%/}"

: "${DEYE_APP_ID:?Set DEYE_APP_ID in .env}"
: "${DEYE_APP_SECRET:?Set DEYE_APP_SECRET in .env}"
: "${DEYE_EMAIL:?Set DEYE_EMAIL in .env}"
: "${DEYE_PASSWORD:?Set DEYE_PASSWORD in .env}"

if command -v shasum >/dev/null 2>&1; then
  PASS_HASH=$(printf '%s' "${DEYE_PASSWORD}" | shasum -a 256 | awk '{print $1}')
else
  PASS_HASH=$(printf '%s' "${DEYE_PASSWORD}" | sha256sum | awk '{print $1}')
fi

echo "=== 1) Deye token ==="
TOKEN_JSON=$(curl -sS -X POST \
  "${DEYE_BASE}/account/token?appId=${DEYE_APP_ID}" \
  -H 'Content-Type: application/json' \
  -d "{\"appSecret\":\"${DEYE_APP_SECRET}\",\"email\":\"${DEYE_EMAIL}\",\"companyId\":${DEYE_COMPANY_ID:-0},\"password\":\"${PASS_HASH}\"}")
echo "${TOKEN_JSON}" | jq '{success, msg, code}'
TOKEN=$(echo "${TOKEN_JSON}" | jq -r '.accessToken // .data.accessToken // empty')
if [[ -z "${TOKEN}" ]]; then
  echo "Token failed" >&2
  exit 1
fi

AUTH="Authorization: Bearer ${TOKEN}"

echo
echo "=== 2) customControl smartLoadRead (optional) ==="
READ_JSON=$(curl -sS -X POST \
  "${DEYE_BASE}/order/customControl" \
  -H "${AUTH}" \
  -H 'Content-Type: application/json' \
  -d '{"deviceSn":"2602114844","content":"{\"cmd\":\"smartLoadRead\"}"}')
echo "${READ_JSON}" | jq .

echo
echo "=== 3) customControl smartLoadSetup — On Grid always on = true ==="
SETUP_JSON=$(curl -sS -X POST \
  "${DEYE_BASE}/order/customControl" \
  -H "${AUTH}" \
  -H 'Content-Type: application/json' \
  -d '{"deviceSn":"2602114844","content":"{\"cmd\":\"smartLoadSetup\",\"onGridAlwaysOn\":true}"}')
echo "${SETUP_JSON}" | jq .

ORDER_ID=$(echo "${SETUP_JSON}" | jq -r '.orderId // empty')
if [[ -n "${ORDER_ID}" && "${ORDER_ID}" != "null" ]]; then
  echo
  echo "=== 4) Poll order ${ORDER_ID} (status 666 = done) ==="
  for _ in $(seq 1 30); do
    ORDER_JSON=$(curl -sS -X GET "${DEYE_BASE}/order/${ORDER_ID}" -H "${AUTH}")
    STATUS=$(echo "${ORDER_JSON}" | jq -r '.status // empty')
    echo "status=${STATUS}"
    if [[ "${STATUS}" == "666" ]]; then
      echo "${ORDER_JSON}" | jq '{status, analysisResult, orderResult, error}'
      break
    fi
    sleep 2
  done
fi
