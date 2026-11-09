#!/usr/bin/env bash
# Build a Play-signed prod AAB for Open EMS (package com.km220.openems).
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app-mobile"
OUT_DIR="${SCRIPT_DIR}/dist-aab"

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
if [ ! -d "$ANDROID_HOME" ]; then
  echo "Error: Android SDK not found at ANDROID_HOME=$ANDROID_HOME"
  exit 1
fi

KEY_PROPS="${APP_DIR}/android/key.properties"
KEYSTORE="${APP_DIR}/android/release.keystore"
if [ ! -f "$KEY_PROPS" ] || [ ! -f "$KEYSTORE" ]; then
  echo "Error: Play upload key missing."
  echo "Copy release.keystore and key.properties from open-ems-publishing-keys.zip"
  echo "into ${APP_DIR}/android/ (see app-mobile/README.md)."
  exit 1
fi

echo "Signing: release keystore (key.properties found)"

cd "$APP_DIR"
CAPACITOR_PLATFORM=android npx cap sync android
cd android
./gradlew bundleProdRelease

AAB_DIR="${APP_DIR}/android/app/build/outputs/bundle/prodRelease"
mkdir -p "$OUT_DIR"
AAB="$(find "$AAB_DIR" -name '*.aab' -print -quit)"
if [ -z "$AAB" ]; then
  echo "Build output dir not found or empty: $AAB_DIR"
  exit 1
fi

cp "$AAB" "${OUT_DIR}/open-ems.aab"
echo ""
echo "Play AAB ready: ${OUT_DIR}/open-ems.aab"
ls -lh "${OUT_DIR}/open-ems.aab"
