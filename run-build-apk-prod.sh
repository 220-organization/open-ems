#!/usr/bin/env bash
# Build shareable prod release APK for Open EMS.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app-mobile"
OUT_DIR="${SCRIPT_DIR}/dist-apk"

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
if [ ! -d "$ANDROID_HOME" ]; then
  echo "Error: Android SDK not found at ANDROID_HOME=$ANDROID_HOME"
  exit 1
fi

KEY_PROPS="${APP_DIR}/android/key.properties"
if [ -f "$KEY_PROPS" ]; then
  echo "Signing: release keystore (key.properties found)"
else
  echo "Signing: debug keystore (key.properties not found — APK is installable but not Play-ready)"
fi

cd "$APP_DIR"
CAPACITOR_PLATFORM=android npx cap sync android
cd android
./gradlew assembleProdRelease
cd ..

APK_DIR="${APP_DIR}/android/app/build/outputs/apk/prod/release"
PUBLIC_APK="${SCRIPT_DIR}/ui/public/download/open-ems.apk"
mkdir -p "$OUT_DIR" "${SCRIPT_DIR}/ui/public/download"

echo ""
if [ -d "$APK_DIR" ]; then
  echo "Copying APK(s) to $OUT_DIR ..."
  cp "${APK_DIR}/"*.apk "$OUT_DIR/" 2>/dev/null || true
  if [ -f "${APK_DIR}/open-ems.apk" ]; then
    cp "${APK_DIR}/open-ems.apk" "$PUBLIC_APK"
    echo "Hosted APK: $PUBLIC_APK"
  fi
  echo ""
  echo "Shareable APK(s) ready:"
  ls -lh "${OUT_DIR}/"*.apk 2>/dev/null || true
else
  echo "Build output dir not found: $APK_DIR"
  exit 1
fi
