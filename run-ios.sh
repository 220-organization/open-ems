#!/usr/bin/env bash
# Run Open EMS Capacitor app on iOS simulator (prod: https://220-km.com:9220).
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app-mobile"

cd "$APP_DIR"
export CAPACITOR_PLATFORM=ios
npx cap sync ios
if [ -d ios/App ] && command -v pod >/dev/null 2>&1; then
  (cd ios/App && pod install)
fi
npx cap run ios
