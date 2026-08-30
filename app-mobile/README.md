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
./run-build-aab-prod.sh   # signed AAB for Google Play → dist-aab/open-ems.aab
```

## Android signing

Copy `android/key.properties.example` → `android/key.properties` and add a release keystore. Without it, **APK** release builds use the debug keystore (installable for testing). **Play Store AAB** (`./run-build-aab-prod.sh`) requires the release keystore — debug-signed bundles are rejected.

Play listing copy, Data safety answers, and privacy URL: [play-store/LISTING.md](play-store/LISTING.md).

Public privacy policy (required by Play): https://220-km.com:9220/privacy.html

## iOS Archive / App Store

Bundle ID: `com.km220.openems` (prod). Team: `4U78HYST9P`. Privacy policy: `https://220-km.com:9220/privacy.html`.

From **open-ems** repo root (macOS with Xcode):

```bash
./run-deploy-ios.sh
```

Or from `app-mobile`:

```bash
npm run ios:archive      # IPA only
npm run ios:testflight   # IPA + upload to App Store Connect
```

Then in [App Store Connect](https://appstoreconnect.apple.com/apps): attach the build, complete the store listing (screenshots, description, age rating, App Privacy), and **Submit for Review**.

**Prerequisites:** signed Apple Developer / Paid Apps agreements (Account Holder → App Store Connect → Business), Xcode (not only Command Line Tools), CocoaPods, Node.js 18+.

Open `ios/App/App.xcworkspace` in Xcode → Product → Archive if you prefer the GUI.
