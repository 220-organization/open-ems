#!/usr/bin/env bash
# Build shareable preprod release APK for Open EMS.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app-mobile"
OUT_DIR="${SCRIPT_DIR}/dist-apk"
CONFIG_JS="${APP_DIR}/capacitor.config.js"
CONFIG_PREPROD_JS="${APP_DIR}/capacitor.config.preprod.js"

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
if [ ! -d "$ANDROID_HOME" ]; then
  echo "Error: Android SDK not found at ANDROID_HOME=$ANDROID_HOME"
  exit 1
fi

cd "$APP_DIR"
cp "$CONFIG_JS" "${CONFIG_JS}.bak"
cp "$CONFIG_PREPROD_JS" "$CONFIG_JS"
trap 'mv "${CONFIG_JS}.bak" "$CONFIG_JS"' EXIT

CAPACITOR_PLATFORM=android npx cap sync android
cd android
./gradlew assemblePreprodRelease
cd ..

APK_DIR="${APP_DIR}/android/app/build/outputs/apk/preprod/release"
mkdir -p "$OUT_DIR"

echo ""
if [ -d "$APK_DIR" ]; then
  echo "Copying APK(s) to $OUT_DIR ..."
  cp "${APK_DIR}/"*.apk "$OUT_DIR/" 2>/dev/null || true
  echo ""
  echo "Shareable APK(s) ready:"
  ls -lh "${OUT_DIR}/"*.apk 2>/dev/null || true
else
  echo "Build output dir not found: $APK_DIR"
  exit 1
fi
