#!/usr/bin/env bash
# Run Open EMS Capacitor app on the iOS simulator (prod: https://220-km.com:9220).
# Same shape as activecharge/run-em-ios.sh: cap sync, then cap run with a simulator id.
# Requires: macOS, Xcode, CocoaPods.

set -euo pipefail

export PATH="${HOME}/.gem/ruby/2.6.0/bin:${PATH}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app-mobile"
# iPhone Duo, iOS 27.1. Override with IOS_TARGET=<udid>.
IOS_TARGET="${IOS_TARGET:-D3077A28-13A1-437F-9E23-D44E1A167234}"
DERIVED="${APP_DIR}/build/ios-sim"

cd "$APP_DIR"
export CAPACITOR_PLATFORM=ios

echo "==> Syncing Capacitor (ios)..."
npx cap sync ios

echo "==> Running iOS app on simulator target ${IOS_TARGET}"
set +e
npx cap run ios --target "${IOS_TARGET}"
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  exit 0
fi

# Xcode 27 can boot a simulator without shipping Simulator.app.
# cap run then fails while opening the window. Install and launch directly.
echo "==> cap run exited ${status}. Installing on the booted simulator..."
xcrun simctl boot "${IOS_TARGET}" 2>/dev/null || true
xcodebuild \
  -workspace ios/App/App.xcworkspace \
  -scheme App \
  -configuration Debug \
  -destination "platform=iOS Simulator,id=${IOS_TARGET}" \
  -derivedDataPath "${DERIVED}" \
  build

APP_PATH="${DERIVED}/Build/Products/Debug-iphonesimulator/App.app"
BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print:CFBundleIdentifier' "${APP_PATH}/Info.plist")"
xcrun simctl install "${IOS_TARGET}" "${APP_PATH}"
xcrun simctl launch "${IOS_TARGET}" "${BUNDLE_ID}"
echo "==> Launched ${BUNDLE_ID} on ${IOS_TARGET}"
