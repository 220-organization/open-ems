#!/usr/bin/env bash
# Increment iOS version, build, and upload Open EMS to App Store Connect.
# Requires macOS, Xcode, CocoaPods, Node.js, and a signed Apple Developer agreement.
#
# Bundle ID: com.km220.openems
# After upload: App Store Connect → the Open EMS app → TestFlight, then Submit for Review.

set -euo pipefail

export CAPACITOR_PLATFORM=ios

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app-mobile"
PBX="${APP_DIR}/ios/App/App.xcodeproj/project.pbxproj"

APP_STORE_CONNECT_API_KEY_ID="${APP_STORE_CONNECT_API_KEY_ID:-3DJ5UR88C2}"
APP_STORE_CONNECT_ISSUER_ID="${APP_STORE_CONNECT_ISSUER_ID:-7406b3c6-c0e2-4518-bdcd-eafa6028da3b}"
KEY_ID="${APP_STORE_CONNECT_API_KEY_ID}"
if [[ -z "${APP_STORE_CONNECT_API_KEY_PATH:-}" ]]; then
  if [[ -f "${APP_DIR}/ios/App/private_keys/AuthKey_${KEY_ID}.p8" ]]; then
    APP_STORE_CONNECT_API_KEY_PATH="${APP_DIR}/ios/App/private_keys/AuthKey_${KEY_ID}.p8"
  elif [[ -f "${SCRIPT_DIR}/../activecharge/app-220km/ios/App/private_keys/AuthKey_${KEY_ID}.p8" ]]; then
    APP_STORE_CONNECT_API_KEY_PATH="${SCRIPT_DIR}/../activecharge/app-220km/ios/App/private_keys/AuthKey_${KEY_ID}.p8"
  elif [[ -f "$HOME/.appstoreconnect/private_keys/AuthKey_${KEY_ID}.p8" ]]; then
    APP_STORE_CONNECT_API_KEY_PATH="$HOME/.appstoreconnect/private_keys/AuthKey_${KEY_ID}.p8"
  fi
fi
export APP_STORE_CONNECT_API_KEY_ID APP_STORE_CONNECT_ISSUER_ID APP_STORE_CONNECT_API_KEY_PATH

if [[ ! -f "$PBX" ]]; then
  echo "Error: project.pbxproj not found at $PBX"
  exit 1
fi

BUILD=$(grep -m1 "CURRENT_PROJECT_VERSION = " "$PBX" | sed 's/.*CURRENT_PROJECT_VERSION = \([0-9]*\).*/\1/')
NEW_BUILD=$((BUILD + 1))
sed -i '' "s/CURRENT_PROJECT_VERSION = ${BUILD};/CURRENT_PROJECT_VERSION = ${NEW_BUILD};/g" "$PBX"
echo "==> Bump build: ${BUILD} → ${NEW_BUILD}"

cd "$APP_DIR"
./scripts/ios-testflight.sh --upload

echo ""
echo "==> Done. In App Store Connect: attach the build, complete listing, Submit for Review."
echo "    https://appstoreconnect.apple.com/apps"
