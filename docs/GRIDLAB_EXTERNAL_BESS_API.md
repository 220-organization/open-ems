# GridLab External BESS API — Open EMS integration

Read-only integration with [GridLab](https://gridlab.com.ua) External BESS API for device **16** (BESS 500/1075 / «БРЕС контейнер 500/1075»).

Vendor docs: https://gridlab.com.ua/docs (section **External BESS API**).

## Purpose

- Live monitoring: battery SoC / power, site meters (PCC, PV, load, EV chargers).
- Hourly history: SoC, per-meter energy deltas; energy-flow aggregates when upstream fills them.
- No control commands — GridLab grants read-only access to registered external endpoints for one device.

## Access

| Parameter | Value |
|-----------|--------|
| Base URL | `https://gridlab.com.ua` (hardcoded) |
| Username | `api_220km` (hardcoded) |
| Password | set via `GRIDLAB_PASSWORD` only (never commit) |
| Device ID | `16` (hardcoded) |
| Rights | read external BESS endpoints only |

## Authentication

1. `POST /api/auth/login` with `{"username","password"}` → `access_token` (JWT).
2. All data requests: `Authorization: Bearer <token>`.
3. Open EMS caches the token until `exp` (minus 60 s). Observed TTL ≈ **5 hours**.
4. On HTTP **401**, the client clears the token, re-logins once, and retries.
5. HTTP **403** is **not** retried (endpoint disabled / device not allowed / missing token often returns 403 in production).

## Upstream endpoints used

Base path: `/api/external/bess/{device_id}`

| Method | Path | Use in Open EMS |
|--------|------|-----------------|
| GET | `/status` | Live SoC, battery power, online, freshness |
| GET | `/meters` | Live PCC / PV / load / EV powers + cumulative kWh |
| GET | `/history/soc` | Hourly SoC (max 7-day range) |
| GET | `/history/meter/{id}` | Hourly meter energy deltas (max 31-day range) |
| GET | `/history/flows` | Hourly energy flows (max 31-day range; may be empty) |

## Sign conventions (aligned with Deye / Power flow UI)

| Field | GridLab | Open EMS |
|-------|---------|----------|
| Battery | `power_kw > 0` discharge, `< 0` charge | `batteryPowerW` same sign (×1000 → W) |
| PCC | `power_kw > 0` import, `< 0` export | `gridPowerW` same sign |
| Production | generation ≥ 0 | `pvPowerW` ≥ 0 |
| Load | consumption ≥ 0 | `loadPowerW` ≥ 0 |

Unmeasured values are `null` / `None` — **never** treat as zero when balancing.

Freshness: prefer `stale: false` and `data_age_seconds` under `GRIDLAB_STALE_MAX_AGE_SEC` (default 60). Stale samples are still returned on live API with `stale: true`; they are **not** written to `gridlab_power_sample`.

## Device 16 meter topology (do not sum by role)

Roles overlap. Always select meters by **explicit IDs** (env defaults below). Skip `is_virtual: true`.

| Role | Preferred ID | Name | Notes |
|------|--------------|------|-------|
| pcc | 21 | Метр Мережа (PCC) | Only PCC |
| production | 23 | Метр СЕС | Whole PV; **do not** also sum 25+26 |
| load | 22 | Метр Навантаження | Site load; **do not** also sum 24 |
| EV | 27, 28 | Зарядка ТОКА 1/2 | Summed into `evPowerW` |
| virtual | 31, 32 | СЕС сумарна / Зарядки ТОКА | Excluded from aggregates |

Overlapping physical meters (do **not** add with preferred IDs):

- Production: 25 (СЕС 1-2), 26 (СЕС 3-4) — subsets of 23.
- Load: 24 (Метр Споживання) — overlaps 22.

**Production meter semantics:** for role `production`, generation appears in `energy_import_kwh` / positive `power_kw` (not “grid import”).

## Open EMS components

| Layer | Path |
|-------|------|
| Settings | `app/settings.py`, `.env.example` (`GRIDLAB_*`) |
| HTTP client | `app/gridlab_api.py` |
| Live normalize + DB samples | `app/gridlab_power_service.py` |
| Hourly backfill | `app/gridlab_history_service.py` |
| Schedulers | `app/gridlab_power_scheduler.py`, `app/gridlab_history_scheduler.py` |
| REST | `app/routers/gridlab_proxy.py` → `/api/gridlab/*` |
| Migration | `db/migration/postgres/common/V33__gridlab_bess.sql` |
| UI | `gridlab:` ESS prefix, `GridLabTotalsPanel.jsx`, Power flow + DAM chart |

### Local REST surface

- `GET /api/gridlab/devices`
- `GET /api/gridlab/soc?deviceId=16` — live SoC for admin-portal SOC dynamic pricing (same `ok` / `socPercent` shape as `/api/deye/soc`)
- `GET /api/gridlab/solar-insolation?lat=&lon=` — today/tomorrow insolation % via Open-Meteo (EV port GPS; GridLab has no plant coordinates)
- `GET /api/gridlab/power-flow?deviceId=16`
- `GET /api/gridlab/meters`
- `GET /api/gridlab/soc-history-day?deviceId=16&date=YYYY-MM-DD`
- `GET /api/gridlab/history/soc|flows|meter/{id}`
- `POST /api/gridlab/history/sync` — body `{ "dateFrom", "dateTo" }`
- `POST /api/gridlab/power-snapshot`

### Schedulers

- Power snapshot every `GRIDLAB_POWER_SNAPSHOT_INTERVAL_SEC` (default 300) → `gridlab_power_sample` (+ `gridlab_meter_reading`).
- History: on startup, if hourly SoC empty → backfill `GRIDLAB_HISTORY_BACKFILL_DAYS` (default 7); then daily at Kyiv hour `GRIDLAB_HISTORY_SYNC_HOUR_KYIV` (default 01:00) sync yesterday + today.

## Environment variables

Only the password is configurable. Device, username, meters, and intervals are hardcoded in `app/settings.py`.

```bash
GRIDLAB_PASSWORD=          # secret — required for GridLab integration
```

On production deploy, set repository secret **`GRIDLAB_PASSWORD`** (Actions → Secrets). The deploy workflow writes it into the server `.env` and `docker-compose.yml` passes it into the `api` container. Without this secret, `GET /api/gridlab/devices` returns `configured: false` and the UI omits GridLab.

### Station binding (driver app + SOC dynamic price)

Bind a port to GridLab BESS via `station.name`:

```text
trackGridlab:16 bat1075kwh
```

Do **not** reuse `trackInverter:` — GridLab device id `16` is indistinguishable from a Deye serial. Admin-portal Ports CRUD and Dynamic Price pickers write this marker; the driver StartPage shows solar/battery cards from `/api/gridlab/power-flow` and insolation from `/api/gridlab/solar-insolation` using the EV port GPS.

Hardcoded defaults (device 16):

| Setting | Value |
|---------|--------|
| Enabled | `true` |
| Base URL | `https://gridlab.com.ua` |
| Username | `api_220km` |
| Device ID | `16` |
| PCC / PV / LOAD meters | `21` / `23` / `22` |
| EV meters | `27,28` |
| Power snapshot interval | 300 s |
| History sync hour (Kyiv) | 01:00 |
| History backfill days | 7 |

## Differences vs vendor written spec (probed 2026-07-30)

| Topic | Spec text | Observed |
|-------|-----------|----------|
| Missing token | HTTP 401 | Often **403** |
| JWT lifetime | (unspecified) | ≈ **5 hours** (`exp - iat`) |
| `/history/flows` | Hourly kWh flows | **`hours: []`** for May–July 2026 on device 16 — code tolerates empty; use `/history/meter/{id}` for energy |
| `/history/soc`, `/history/meter/{id}` | Present | Working; Kyiv `target_date` + `hour`; future hours may be `null` |
| Other device id | — | Device 15 → **403** |
| Bad meter id | 404 | Confirmed |
| Future date range | 422 | Confirmed |

## Error codes (upstream)

| Code | Meaning |
|------|---------|
| 401 | Token missing/expired (re-login + retry once) |
| 403 | Endpoint/device not allowed (no retry) |
| 404 | Meter missing or not on allowed device |
| 422 | Date range too long or in the future |
| 503 | Telemetry temporarily unavailable |

## Recommendations

- Do not interpret `null` as zero.
- Check `stale` / `data_age_seconds` before using live values for control or balance math.
- Exclude virtual meters; never sum all meters of a role on device 16.
- Cache JWT until near expiry.
- Request history in chunks within vendor limits (7 d SoC, 31 d meter/flows).
