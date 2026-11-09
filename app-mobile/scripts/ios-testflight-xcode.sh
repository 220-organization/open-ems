#!/usr/bin/env bash
# Open the Open EMS iOS project in Xcode for a manual TestFlight upload.
# Run from app-mobile.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$APP_DIR"
export CAPACITOR_PLATFORM=ios

echo "==> Syncing Capacitor (ios)..."
npm run cap:sync:ios

echo "==> Opening Xcode..."
npx cap open ios

echo ""
echo "In Xcode:"
echo "  1. Destination: Any iOS Device (arm64)"
echo "  2. Product → Archive"
echo "  3. Organizer → Distribute App → App Store Connect → Upload"
echo "  4. App Store Connect → TestFlight (build appears in 5–15 min)"
echo ""
