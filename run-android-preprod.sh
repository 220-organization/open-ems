#!/usr/bin/env bash
# Run Open EMS on Android emulator with preprod config.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app-mobile"
CONFIG_JS="${APP_DIR}/capacitor.config.js"
CONFIG_PREPROD_JS="${APP_DIR}/capacitor.config.preprod.js"

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
if [ ! -d "$ANDROID_HOME" ]; then
  echo "Error: Android SDK not found at ANDROID_HOME=$ANDROID_HOME"
  exit 1
fi

cd "$APP_DIR"
if [[ ! -f "$CONFIG_PREPROD_JS" ]]; then
  echo "Error: $CONFIG_PREPROD_JS not found"
  exit 1
fi
cp "$CONFIG_JS" "${CONFIG_JS}.bak"
cp "$CONFIG_PREPROD_JS" "$CONFIG_JS"
trap 'mv "${CONFIG_JS}.bak" "$CONFIG_JS"' EXIT

CAPACITOR_PLATFORM=android npx cap sync android
npx cap run android --flavor preprod
