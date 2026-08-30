#!/usr/bin/env bash
# Build a signed Android App Bundle (AAB) for Google Play — Open EMS prod flavor.
# Requires: Android SDK (ANDROID_HOME), Java 17+, app-mobile/android/key.properties + keystore.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app-mobile"
OUT_DIR="${SCRIPT_DIR}/dist-aab"

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
if [ ! -d "$ANDROID_HOME" ]; then
  echo "Error: Android SDK not found at ANDROID_HOME=$ANDROID_HOME"
  exit 1
fi

KEY_PROPS="${APP_DIR}/android/key.properties"
if [ ! -f "$KEY_PROPS" ]; then
  echo "Error: $KEY_PROPS is missing."
  echo "Google Play rejects debug-signed bundles. Copy key.properties.example,"
  echo "create android/release.keystore, then re-run. See app-mobile/play-store/LISTING.md"
  exit 1
fi

echo "Signing: release keystore (key.properties found)"

cd "$APP_DIR"
if [ ! -d node_modules ]; then
  npm install
fi
CAPACITOR_PLATFORM=android npx cap sync android
cd android
./gradlew bundleProdRelease
cd ..

AAB_DIR="${APP_DIR}/android/app/build/outputs/bundle/prodRelease"
mkdir -p "$OUT_DIR"

echo ""
if [ ! -d "$AAB_DIR" ]; then
  echo "Build output dir not found: $AAB_DIR"
  exit 1
fi

shopt -s nullglob
AABS=("${AAB_DIR}"/*.aab)
if [ ${#AABS[@]} -eq 0 ]; then
  echo "No .aab found in $AAB_DIR"
  exit 1
fi

cp "${AABS[@]}" "$OUT_DIR/"
if [ -f "${AAB_DIR}/app-prod-release.aab" ]; then
  cp "${AAB_DIR}/app-prod-release.aab" "${OUT_DIR}/open-ems.aab"
elif [ -f "${AAB_DIR}/app-release.aab" ]; then
  cp "${AAB_DIR}/app-release.aab" "${OUT_DIR}/open-ems.aab"
else
  cp "${AABS[0]}" "${OUT_DIR}/open-ems.aab"
fi

echo "Play Store AAB ready:"
ls -lh "${OUT_DIR}/"*.aab
echo ""
echo "Upload ${OUT_DIR}/open-ems.aab in Play Console → Test and release."
echo "Privacy policy: https://220-km.com:9220/privacy.html"
