# Open EMS — Google Play listing

Package: `com.km220.openems`  
Privacy policy URL (paste in Play Console): **https://220-km.com:9220/privacy.html**  
Default store listing language: English. Add Ukrainian as a localized listing.

## Store listing copy

### App name (max 30)

Open EMS

Ukrainian: Вирій ЕМС

### Short description (max 80)

English:

```
Smart EMS: solar, BESS, EV charging, DAM/IDM arbitrage and live power flow.
```

Ukrainian:

```
Розумний EMS: СЕС, BESS, EV, арбітраж РДН/ВДР і живі потоки потужності.
```

### Full description

English:

```
Open EMS is an open-source energy management system for solar, battery (BESS) and EV charging sites.

Monitor live power flow — grid, PV, battery SoC, load and EV ports — from Deye, Huawei FusionSolar and other connected sources. Run automated charge and discharge scenarios against day-ahead (DAM) and intraday (IDM) prices (OREE in Ukraine, ENTSO-E overlays for ES/PL). Use ML solar and price forecasts, peak shaving, island-mode planning and ROI analytics.

The app opens your Open EMS dashboard over HTTPS. Browse the public control panel without an account. Connecting your own inverter uses that vendor’s cloud API (for example Deye Cloud or Huawei FusionSolar).

Self-hosted source: https://github.com/220-organization/open-ems
Web: https://220-km.com:9220/
```

Ukrainian:

```
Вирій ЕМС — відкрита система керування енергією для СЕС, батарей (BESS) і зарядки електромобілів.

Дивіться живі потоки потужності — мережа, PV, SoC батареї, навантаження і EV-порти — з Deye, Huawei FusionSolar та інших джерел. Автоматичні сценарії заряду/розряду за цінами РДН і ВДР (OREE в Україні, ENTSO-E для ES/PL). ML-прогноз генерації та цін, зрізання піків, острівний режим і ROI.

Застосунок відкриває панель Open EMS по HTTPS. Переглядати демо можна без облікового запису. Підключення власного інвертора йде через хмарний API виробника (Deye Cloud, Huawei FusionSolar).

Код: https://github.com/220-organization/open-ems
Веб: https://220-km.com:9220/
```

## Graphics

| Asset | Size | Notes |
|-------|------|--------|
| High-res icon | 512 × 512 PNG | `play-store/icon-512.png` |
| Feature graphic | 1024 × 500 PNG | `play-store/feature-graphic.png` |
| Phone screenshots | at least 2 | Capture Control Panel, DAM chart, landing. JPEG/PNG, 16:9 or 9:16 |

## Play Console declarations

### App category

Maps & Navigation is wrong. Use **Tools** or **Productivity**. Tags: energy, solar, battery.

### App access

All core screens (power flow, DAM chart, about) work **without login**. Optional: connecting a private inverter needs that vendor’s account. You can leave “all functionality available without special access”.

### Ads

No ads.

### Content rating

Questionnaire: utility / tools, no user-generated public chat in the shell, no violence. Expected rating: **Everyone** / PEGI 3.

### Target audience

Age 18+ (energy assets / B2B). Not designed for children.

### News / COVID / government

No.

### Data safety (declare these)

Collected (not sold):

| Data type | Purpose | Optional? | Shared |
|-----------|---------|-----------|--------|
| App interactions, diagnostics (Clarity, if enabled) | Analytics | Yes (product analytics) | Microsoft |
| Personal info you type in callback / marketplace forms (name, phone, email) | App functionality | Yes | No (except hosting) |
| Inverter telemetry the user connects | App functionality | Yes | Vendor cloud (Deye / Huawei) when user connects |
| Device or other IDs (local client id, language) | App functionality | No (on-device) | No |

- Encrypted in transit: **Yes** (HTTPS)
- Users can request deletion: **Yes** — sales@220-km.com
- Advertising ID: **No**
- Location / camera / contacts / photos: **No**

If `REACT_APP_CLARITY_PROJECT_ID` is set in production, also tick **Screenshots / session recordings** (Clarity). If it is empty, omit analytics rows.

### Financial features

The app does not process Play Billing. Marketplace / consultation payments, if any, happen on the website — declare “not using Play billing” if you do not sell in-app.

## Upload

1. One-time signing (keep the keystore off git):

```bash
keytool -genkey -v -keystore app-mobile/android/release.keystore \
  -alias openems -keyalg RSA -keysize 2048 -validity 10000
cp app-mobile/android/key.properties.example app-mobile/android/key.properties
# fill storeFile=../release.keystore and passwords
```

2. Build the Play bundle (requires key.properties):

```bash
./run-build-aab-prod.sh
```

Output: `dist-aab/open-ems.aab`

3. Play Console → Open EMS → **Testing** (internal) first → upload AAB → then Production when testers are happy.

4. Dashboard → **App content** → Privacy policy URL: `https://220-km.com:9220/privacy.html`

## Target API

This release targets **Android 16 (API 36)** (Google Play requirement for new apps and updates from 31 August 2026). Capacitor 8 is required for that target.
