# Open EMS — Native App (Capacitor)

WebView wrapper for the [Open EMS](https://220-km.com:9220/) dashboard. Same pattern as `app-220km` in the monorepo.

## Tech stack

- **Capacitor 6** — native iOS / Android shell
- **Remote URL** — no bundled React build (`server.url` in `capacitor.config.js`)

| Config | URL |
|--------|-----|
| prod | `https://220-km.com:9220` |
| preprod | `https://220-km-preprod.com:9220` |
| localhost | `http://localhost:9220` (run `./run-local.sh` first) |

## Prerequisites

- Node.js 18+
- **iOS:** macOS, Xcode, CocoaPods (`cd ios/App && pod install`)
- **Android:** Android SDK (`ANDROID_HOME`), Java 17

## Quick start

```bash
cd app-mobile
npm install
CAPACITOR_PLATFORM=ios npx cap sync ios      # macOS only
CAPACITOR_PLATFORM=android npx cap sync android
```

From **open-ems** repo root:

```bash
./run-ios.sh              # prod on iOS simulator
./run-ios-preprod.sh      # preprod
./run-ios-localhost.sh    # local UI (9220)
./run-android.sh          # prod on Android emulator
./run-android-preprod.sh
./run-build-apk-prod.sh   # → dist-apk/open-ems.apk
./run-build-apk-preprod.sh
```

## Android signing

Copy `android/key.properties.example` → `android/key.properties` and add a release keystore. Without it, release builds use the debug keystore (installable for testing).

## iOS Archive / TestFlight

Open `ios/App/App.xcworkspace` in Xcode → Product → Archive.

Bundle IDs: `com.km220.openems` (prod), `com.km220.openems.preprod` (preprod scheme — add manually if needed).
