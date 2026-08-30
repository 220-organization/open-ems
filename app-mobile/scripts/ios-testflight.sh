#!/usr/bin/env bash
# Build iOS app and optionally upload to App Store Connect (TestFlight).
# Run from app-mobile root.
#
# Usage:
#   ./scripts/ios-testflight.sh              # build + export IPA only
#   ./scripts/ios-testflight.sh --upload     # build + export + upload
#
# For upload, set:
#   APP_STORE_CONNECT_API_KEY_ID
#   APP_STORE_CONNECT_ISSUER_ID
#   APP_STORE_CONNECT_API_KEY_PATH (or put AuthKey_<KEY_ID>.p8 in ~/.appstoreconnect/private_keys/)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IOS_APP="$APP_DIR/ios/App"
ARCHIVE_PATH="$APP_DIR/build/ios/App.xcarchive"
EXPORT_PATH="$APP_DIR/build/ios/export"
EXPORT_OPTIONS="$APP_DIR/ios/ExportOptions.plist"

cd "$APP_DIR"

echo "==> Syncing Capacitor (ios)..."
npm run cap:sync:ios

if command -v pod >/dev/null 2>&1; then
  echo "==> pod install..."
  (cd "$IOS_APP" && pod install)
fi

echo "==> Building archive..."
cd "$IOS_APP"
xcodebuild -workspace App.xcworkspace \
  -scheme App \
  -configuration Release \
  -archivePath "$ARCHIVE_PATH" \
  -destination 'generic/platform=iOS' \
  -allowProvisioningUpdates \
  archive

echo "==> Exporting IPA..."
rm -rf "$EXPORT_PATH"
mkdir -p "$EXPORT_PATH"
xcodebuild -exportArchive \
  -archivePath "$ARCHIVE_PATH" \
  -exportPath "$EXPORT_PATH" \
  -exportOptionsPlist "$EXPORT_OPTIONS" \
  -allowProvisioningUpdates

IPA_PATH="$EXPORT_PATH/App.ipa"
if [[ ! -f "$IPA_PATH" ]]; then
  echo "Error: IPA not found at $IPA_PATH"
  exit 1
fi
echo "==> IPA ready: $IPA_PATH"

if [[ "${1:-}" == "--upload" ]]; then
  if [[ -z "${APP_STORE_CONNECT_API_KEY_ID:-}" ]] || [[ -z "${APP_STORE_CONNECT_ISSUER_ID:-}" ]]; then
    echo "For upload set: APP_STORE_CONNECT_API_KEY_ID, APP_STORE_CONNECT_ISSUER_ID"
    echo "Optional: APP_STORE_CONNECT_API_KEY_PATH"
    exit 1
  fi
  echo "==> Uploading to App Store Connect..."
  KEY_PATH="${APP_STORE_CONNECT_API_KEY_PATH:-$HOME/.appstoreconnect/private_keys/AuthKey_${APP_STORE_CONNECT_API_KEY_ID}.p8}"
  if [[ ! -f "$KEY_PATH" ]]; then
    echo "Error: API key file not found: $KEY_PATH"
    exit 1
  fi
  xcrun altool --upload-app \
    -f "$IPA_PATH" \
    -t ios \
    --apiKey "$APP_STORE_CONNECT_API_KEY_ID" \
    --apiIssuer "$APP_STORE_CONNECT_ISSUER_ID" \
    --apiKeyPath "$KEY_PATH"
  echo "==> Upload finished. Check App Store Connect → TestFlight, then submit for App Review."
else
  echo "To upload this build run: $0 --upload"
fi
