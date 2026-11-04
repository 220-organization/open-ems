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

Play package `com.km220.openems` is signed with the upload keystore `android/release.keystore` plus `android/key.properties` (`storeFile=../release.keystore`, alias `openems`). Both files are gitignored. Without them, release builds fall back to the debug keystore, which Google Play will reject.

A fresh clone does not contain the keystore. Restore it from `open-ems-publishing-keys.zip` (see below) or copy the same two files from the private `activecharge` checkout at `open-ems-android-signing/`.

## Publish a new version from a new laptop

The Play upload key and the App Store Connect API key are not in the `open-ems` git history. Take `open-ems-publishing-keys.zip` from the previous machine (keep it offline; it contains the keystore passwords).

### Machine setup

- macOS
- Xcode (iOS) and CocoaPods (`cd app-mobile/ios/App && pod install`)
- Android SDK (`ANDROID_HOME`, default `$HOME/Library/Android/sdk`) and Java 17
- Node.js 18+
- Clone this repo

### Restore the keys

Unzip `open-ems-publishing-keys.zip` and copy:

| File in the zip | Destination |
|-----------------|-------------|
| `android/release.keystore` | `app-mobile/android/release.keystore` |
| `android/key.properties` | `app-mobile/android/key.properties` |
| `ios/AuthKey_3DJ5UR88C2.p8` | `app-mobile/ios/App/private_keys/AuthKey_3DJ5UR88C2.p8` |

`key.properties` is already pointed at `../release.keystore` relative to `android/app/`. Do not commit these files.

There is no Apple Distribution `.p12` in the zip. Signing is automatic. The first `./run-deploy-ios.sh` on the new Mac creates the distribution certificate with App Store Connect API key `3DJ5UR88C2` (issuer `7406b3c6-c0e2-4518-bdcd-eafa6028da3b`, team `4U78HYST9P`). The same `.p8` is the 220 km upload key. If the sibling `activecharge` checkout is next to this repo, `./run-deploy-ios.sh` also finds that copy and the explicit copy above is optional.

### Android (Google Play closed testing)

In `app-mobile/android/app/build.gradle`, raise `versionCode` above the code already on the track, and set `versionName`.

From the **open-ems** repo root:

```bash
./run-build-aab-prod.sh
```

Upload `dist-aab/open-ems.aab` to the closed testing track:

https://play.google.com/console/u/1/developers/4654009373618050620/app/4972630949619930674/tracks/4700348587022846783

Testers install from https://play.google.com/apps/testing/com.km220.openems after they opt in with a Google account that is on the track list.

### iOS (TestFlight)

From the **open-ems** repo root, on macOS with Xcode:

```bash
./run-deploy-ios.sh
```

That bumps `CURRENT_PROJECT_VERSION` and `MARKETING_VERSION`, archives, and uploads to TestFlight. Details are in the next section.

## iOS Archive / TestFlight

iOS bundle ID uploaded to App Store Connect: `com.km220.vibe.ChargingLiveActivity` (app [6806645777](https://appstoreconnect.apple.com/apps/6806645777/distribution)). Team: `4U78HYST9P`. Android stays `com.km220.openems`. `cap sync` rewrites the Xcode bundle ID from `capacitor.config.js`; `scripts/ios-testflight.sh` sets the App Store ID again before archive. Marketing version and build number live in `ios/App/App.xcodeproj/project.pbxproj` (`MARKETING_VERSION`, `CURRENT_PROJECT_VERSION`).

From the **open-ems** repo root, on macOS with Xcode:

```bash
./run-deploy-ios.sh
```

That bumps the build and marketing version, archives, exports an IPA, and uploads it to TestFlight. The script reuses the App Store Connect API key already used by 220 km (`AuthKey_3DJ5UR88C2.p8`). Search order:

1. `app-mobile/ios/App/private_keys/`
2. `app-mobile/ios/private_keys/`
3. `~/.appstoreconnect/private_keys/`
4. `~/Downloads/`
5. the 220 km copy in the sibling `activecharge` checkout

Archive only (no upload), from `app-mobile`:

```bash
npm run ios:archive
npm run ios:testflight   # archive + upload
npm run ios:xcode        # open the workspace for a manual Organizer upload
```

App Store Connect must already contain an iOS app whose bundle ID is `com.km220.openems`. The record named **Open EMS** (`6806645777`) is not that app: its bundle ID is `com.km220.vibe.ChargingLiveActivity` (the 220 km Live Activity extension). Do not ship Open EMS under that identifier.

Registering a new bundle ID is blocked until the Account Holder accepts the latest Apple Developer Program License Agreement at [developer.apple.com/account](https://developer.apple.com/account). After that, create the identifier `com.km220.openems` and a new App Store Connect app, then run `./run-deploy-ios.sh`.

The App Store rejects icons with an alpha channel. `AppIcon-512@2x.png` is 1024×1024 and opaque.
