#!/usr/bin/env bash
# Run Open EMS Capacitor app on Android emulator (prod).
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app-mobile"

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
if [ ! -d "$ANDROID_HOME" ]; then
  echo "Error: Android SDK not found at ANDROID_HOME=$ANDROID_HOME"
  exit 1
fi

cd "$APP_DIR"
CAPACITOR_PLATFORM=android npx cap sync android
npx cap run android --flavor prod
