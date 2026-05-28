#!/usr/bin/env bash
# Run Open EMS on iOS simulator against local UI (http://localhost:9220).
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app-mobile"
CONFIG_JS="${APP_DIR}/capacitor.config.js"
CONFIG_LOCAL_JS="${APP_DIR}/capacitor.config.localhost.js"

cd "$APP_DIR"
if [[ ! -f "$CONFIG_LOCAL_JS" ]]; then
  echo "Error: $CONFIG_LOCAL_JS not found"
  exit 1
fi
cp "$CONFIG_JS" "${CONFIG_JS}.bak"
cp "$CONFIG_LOCAL_JS" "$CONFIG_JS"
trap 'mv "${CONFIG_JS}.bak" "$CONFIG_JS"' EXIT

export CAPACITOR_PLATFORM=ios
npx cap sync ios
if [ -d ios/App ] && command -v pod >/dev/null 2>&1; then
  (cd ios/App && pod install)
fi
npx cap run ios
