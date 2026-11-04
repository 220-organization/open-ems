#!/usr/bin/env bash
# Build the Open EMS iOS app and optionally upload it to TestFlight.
# Run from app-mobile (or via npm run ios:archive / ios:testflight).
#
# Prerequisites:
#   - macOS with Xcode
#   - Apple Developer team 4U78HYST9P
#   - App Store Connect app 6806645777 (bundle ID com.km220.vibe.ChargingLiveActivity)
#   - For upload: App Store Connect API key
#
# Usage:
#   ./scripts/ios-testflight.sh              # build + export IPA only
#   ./scripts/ios-testflight.sh --upload     # build + export + upload to TestFlight
#
# Upload credentials (defaults match the 220 km key):
#   APP_STORE_CONNECT_API_KEY_ID
#   APP_STORE_CONNECT_ISSUER_ID
#   APP_STORE_CONNECT_API_KEY_PATH

set -e

# User gems are not on the default non-interactive PATH.
export PATH="${HOME}/.gem/ruby/2.6.0/bin:${PATH}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IOS_APP="$APP_DIR/ios/App"
ARCHIVE_PATH="$APP_DIR/build/ios/App.xcarchive"
EXPORT_PATH="$APP_DIR/build/ios/export"
EXPORT_OPTIONS="$APP_DIR/ios/ExportOptions.plist"

export CAPACITOR_PLATFORM=ios
cd "$APP_DIR"

echo "==> Syncing Capacitor (ios)..."
npm run cap:sync:ios

# cap sync writes appId (com.km220.openems) into the Xcode project.
# App Store Connect record 6806645777 uses the Live Activity bundle ID.
ASC_BUNDLE_ID="${IOS_BUNDLE_ID:-com.km220.vibe.ChargingLiveActivity}"
PBX="$IOS_APP/App.xcodeproj/project.pbxproj"
sed -i '' "s/PRODUCT_BUNDLE_IDENTIFIER = com.km220.openems;/PRODUCT_BUNDLE_IDENTIFIER = ${ASC_BUNDLE_ID};/g" "$PBX"
echo "==> iOS bundle ID: ${ASC_BUNDLE_ID}"

KEY_ID="${APP_STORE_CONNECT_API_KEY_ID:-3DJ5UR88C2}"
ISSUER_ID="${APP_STORE_CONNECT_ISSUER_ID:-7406b3c6-c0e2-4518-bdcd-eafa6028da3b}"
if [[ -z "${APP_STORE_CONNECT_API_KEY_PATH:-}" ]]; then
  REPO_ROOT="$(cd "$APP_DIR/.." && pwd)"
  CANDIDATES=(
    "${APP_DIR}/ios/App/private_keys/AuthKey_${KEY_ID}.p8"
    "${APP_DIR}/ios/private_keys/AuthKey_${KEY_ID}.p8"
    "$HOME/.appstoreconnect/private_keys/AuthKey_${KEY_ID}.p8"
    "$HOME/Downloads/AuthKey_${KEY_ID}.p8"
    "${REPO_ROOT}/../activecharge/app-220km/ios/App/private_keys/AuthKey_${KEY_ID}.p8"
    "${REPO_ROOT}/../activecharge/app-220km/ios/private_keys/AuthKey_${KEY_ID}.p8"
  )
  for candidate in "${CANDIDATES[@]}"; do
    if [[ -f "$candidate" ]]; then
      APP_STORE_CONNECT_API_KEY_PATH="$candidate"
      break
    fi
  done
fi
AUTH_ARGS=()
if [[ -n "${APP_STORE_CONNECT_API_KEY_PATH:-}" && -f "$APP_STORE_CONNECT_API_KEY_PATH" ]]; then
  AUTH_ARGS=(
    -authenticationKeyPath "$APP_STORE_CONNECT_API_KEY_PATH"
    -authenticationKeyID "$KEY_ID"
    -authenticationKeyIssuerID "$ISSUER_ID"
  )
fi

echo "==> Building archive..."
cd "$IOS_APP"
xcodebuild -workspace App.xcworkspace \
  -scheme App \
  -configuration Release \
  -archivePath "$ARCHIVE_PATH" \
  -destination 'generic/platform=iOS' \
  -allowProvisioningUpdates \
  "${AUTH_ARGS[@]}" \
  archive

echo "==> Exporting IPA..."
rm -rf "$EXPORT_PATH"
mkdir -p "$EXPORT_PATH"
xcodebuild -exportArchive \
  -archivePath "$ARCHIVE_PATH" \
  -exportPath "$EXPORT_PATH" \
  -exportOptionsPlist "$EXPORT_OPTIONS" \
  -allowProvisioningUpdates \
  "${AUTH_ARGS[@]}"

IPA_PATH="$EXPORT_PATH/App.ipa"
if [[ ! -f "$IPA_PATH" ]]; then
  echo "Error: IPA not found at $IPA_PATH"
  exit 1
fi
echo "==> IPA ready: $IPA_PATH"

if [[ "$1" == "--upload" ]]; then
  if [[ -z "${APP_STORE_CONNECT_API_KEY_PATH:-}" || ! -f "$APP_STORE_CONNECT_API_KEY_PATH" ]]; then
    echo "Error: App Store Connect API key not found (AuthKey_${KEY_ID}.p8)."
    exit 1
  fi
  echo "==> Uploading to App Store Connect (TestFlight)..."
  # This altool looks for AuthKey_<id>.p8 in ios/App/private_keys (cwd after the archive).
  mkdir -p "$IOS_APP/private_keys"
  ln -sfn "$APP_STORE_CONNECT_API_KEY_PATH" "$IOS_APP/private_keys/AuthKey_${KEY_ID}.p8"
  xcrun altool --upload-app \
    -f "$IPA_PATH" \
    -t ios \
    --apiKey "$KEY_ID" \
    --apiIssuer "$ISSUER_ID" \
    --apiKeyPath "$(dirname "$APP_STORE_CONNECT_API_KEY_PATH")"
  echo "==> Upload finished. Check App Store Connect → TestFlight for the build."
else
  echo "To upload this build to TestFlight run: $0 --upload"
fi
