#!/usr/bin/env bash
# Increment the Open EMS iOS version, archive, and upload to TestFlight.
# Run from the open-ems repo root on macOS.
#
# Uploads go to App Store Connect app 6806645777 (Open EMS).
# That record's bundle ID is com.km220.vibe.ChargingLiveActivity.

set -e

export PATH="${HOME}/.gem/ruby/2.6.0/bin:${PATH}"
export CAPACITOR_PLATFORM=ios

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app-mobile"
PBX="${APP_DIR}/ios/App/App.xcodeproj/project.pbxproj"
BUNDLE_ID="${IOS_BUNDLE_ID:-com.km220.vibe.ChargingLiveActivity}"

APP_STORE_CONNECT_API_KEY_ID="${APP_STORE_CONNECT_API_KEY_ID:-3DJ5UR88C2}"
APP_STORE_CONNECT_ISSUER_ID="${APP_STORE_CONNECT_ISSUER_ID:-7406b3c6-c0e2-4518-bdcd-eafa6028da3b}"
KEY_ID="${APP_STORE_CONNECT_API_KEY_ID}"

if [[ -z "$APP_STORE_CONNECT_API_KEY_PATH" ]]; then
  CANDIDATES=(
    "${APP_DIR}/ios/App/private_keys/AuthKey_${KEY_ID}.p8"
    "${APP_DIR}/ios/private_keys/AuthKey_${KEY_ID}.p8"
    "$HOME/.appstoreconnect/private_keys/AuthKey_${KEY_ID}.p8"
    "$HOME/Downloads/AuthKey_${KEY_ID}.p8"
    "${SCRIPT_DIR}/../activecharge/app-220km/ios/App/private_keys/AuthKey_${KEY_ID}.p8"
    "${SCRIPT_DIR}/../activecharge/app-220km/ios/private_keys/AuthKey_${KEY_ID}.p8"
  )
  for candidate in "${CANDIDATES[@]}"; do
    if [[ -f "$candidate" ]]; then
      APP_STORE_CONNECT_API_KEY_PATH="$candidate"
      break
    fi
  done
fi
export APP_STORE_CONNECT_API_KEY_ID APP_STORE_CONNECT_ISSUER_ID APP_STORE_CONNECT_API_KEY_PATH

if [[ ! -f "$PBX" ]]; then
  echo "Error: project.pbxproj not found at $PBX"
  exit 1
fi
if [[ -z "$APP_STORE_CONNECT_API_KEY_PATH" || ! -f "$APP_STORE_CONNECT_API_KEY_PATH" ]]; then
  echo "Error: App Store Connect API key not found (AuthKey_${KEY_ID}.p8)."
  exit 1
fi

echo "==> Checking App Store Connect for ${BUNDLE_ID}..."
APP_STORE_APP_ID="$(
  APP_STORE_CONNECT_API_KEY_PATH="$APP_STORE_CONNECT_API_KEY_PATH" \
  APP_STORE_CONNECT_API_KEY_ID="$APP_STORE_CONNECT_API_KEY_ID" \
  APP_STORE_CONNECT_ISSUER_ID="$APP_STORE_CONNECT_ISSUER_ID" \
  python3 - "$BUNDLE_ID" <<'PY'
import json, os, sys, time, base64, urllib.request, urllib.error
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

bundle_id = sys.argv[1]
key_path = os.environ["APP_STORE_CONNECT_API_KEY_PATH"]
kid = os.environ["APP_STORE_CONNECT_API_KEY_ID"]
iss = os.environ["APP_STORE_CONNECT_ISSUER_ID"]

def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

now = int(time.time())
header = {"alg": "ES256", "kid": kid, "typ": "JWT"}
payload = {"iss": iss, "iat": now, "exp": now + 900, "aud": "appstoreconnect-v1"}
signing_input = (
    f"{b64(json.dumps(header, separators=(',', ':')).encode())}."
    f"{b64(json.dumps(payload, separators=(',', ':')).encode())}"
).encode()
key = serialization.load_pem_private_key(open(key_path, "rb").read(), password=None)
der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
r, s = utils.decode_dss_signature(der)
sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
token = signing_input.decode() + "." + b64(sig)

url = (
    "https://api.appstoreconnect.apple.com/v1/apps"
    f"?filter[bundleId]={bundle_id}&limit=5&fields[apps]=name,bundleId"
)
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.load(resp)
except urllib.error.HTTPError as exc:
    detail = exc.read().decode()[:500]
    print(f"App Store Connect request failed ({exc.code}): {detail}", file=sys.stderr)
    sys.exit(1)

matches = [
    item for item in body.get("data", [])
    if item.get("attributes", {}).get("bundleId") == bundle_id
]
if not matches:
    print(
        f"No App Store Connect app with bundle ID {bundle_id}.\n"
        "The record named Open EMS (6806645777) uses "
        "com.km220.vibe.ChargingLiveActivity and cannot receive this build.\n"
        "Accept the Apple Developer Program License Agreement, register "
        f"{bundle_id}, create the app, then rerun.",
        file=sys.stderr,
    )
    sys.exit(1)
print(matches[0]["id"])
PY
)"

BUILD=$(grep -m1 "CURRENT_PROJECT_VERSION = " "$PBX" | sed 's/.*CURRENT_PROJECT_VERSION = \([0-9]*\).*/\1/')
NEW_BUILD=$((BUILD + 1))
sed -i '' "s/CURRENT_PROJECT_VERSION = ${BUILD};/CURRENT_PROJECT_VERSION = ${NEW_BUILD};/g" "$PBX"
echo "==> Bump build: ${BUILD} → ${NEW_BUILD}"

VER=$(grep -m1 "MARKETING_VERSION = " "$PBX" | sed 's/.*MARKETING_VERSION = \([0-9.]*\).*/\1/')
MAJOR="${VER%.*}"
LAST="${VER##*.}"
NEW_VER="${MAJOR}.$((LAST + 1))"
sed -i '' "s/MARKETING_VERSION = ${VER};/MARKETING_VERSION = ${NEW_VER};/g" "$PBX"
echo "==> Bump version: ${VER} → ${NEW_VER}"

cd "$APP_DIR"
./scripts/ios-testflight.sh --upload

echo ""
echo "==> Done. Check TestFlight: https://appstoreconnect.apple.com/teams/${APP_STORE_CONNECT_ISSUER_ID}/apps/${APP_STORE_APP_ID}/testflight/ios"
