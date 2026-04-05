# ENTSO-E Transparency Platform — day-ahead prices (DAM)

This document describes how Open EMS pulls **day-ahead market (DAM) energy prices** for **Spain** and **Poland** bidding zones from the **ENTSO-E Transparency Platform** REST API and stores them in PostgreSQL (`entsoe_dam_price`). More zones can be enabled via **`ENTSOE_DAM_ZONE_EICS`** (comma-separated EIC codes).

## Prerequisites

1. **Registered user** on [Transparency Platform](https://transparency.entsoe.eu/) (Sign In / Register).
2. **RESTful API access** approved by ENTSO-E (email `transparency@entsoe.eu` with subject “RESTful API access” — see [How to get security token?](https://transparencyplatform.zendesk.com/hc/en-us/articles/12845911031188-How-to-get-security-token)).
3. **Security token**: after access is granted, sign in to the **classic** portal → **My Account** → **Generate (new) token** (not only the new R3 UI). Direct link (when logged in): [myAccountSettings](https://transparency.entsoe.eu/usrm/user/myAccountSettings).

## API

- **Base URL (production):** `https://web-api.tp.entsoe.eu/api`  
- **Authentication:** query parameter `securityToken=<token>` (or HTTP header `SECURITY_TOKEN` — Open EMS uses the query form).
- **Dataset:** Energy Prices [12.1.D] — **DocumentType `A44`**, **ProcessType `A01`** (day-ahead).  
- **Reference:** [Sitemap for Restful API Integration](https://transparencyplatform.zendesk.com/hc/en-us/articles/15692855254548), [Postman documentation](https://documenter.getpostman.com/view/7009892/2s93JtP3F6).

## Default bidding zones (EIC)

| Country | Alias | Bidding zone EIC   | Delivery window TZ |
|---------|-------|--------------------|--------------------|
| Spain   | ES    | `10YES-REE------0` | `Europe/Madrid`    |
| Poland  | PL    | `10YPL-AREA-----S` | `Europe/Warsaw`    |

Zones may publish **15-minute** price points in the XML; Open EMS collapses them to **24 hourly** values for the chart. Override or extend zones with env **`ENTSOE_DAM_ZONE_EICS`** (comma-separated EIC codes) and map aliases in code (`ENTSOE_ZONE_ALIASES` / `ENTSOE_DOMAIN_TIMEZONE`).

## Open EMS configuration

| Variable | Meaning |
|----------|---------|
| `ENTSOE_SECURITY_TOKEN` | Transparency Platform security token (required for HTTP pulls). |
| `ENTSOE_API_BASE_URL` | Default `https://web-api.tp.entsoe.eu/api`. |
| `ENTSOE_DAM_ZONE_EICS` | Optional comma-separated EIC list (defaults to Spain + Poland). |
| `ENTSOE_DAM_DAILY_SYNC_ENABLED` | `1` (default) to run background sync at Brussels hours; set `0` to disable. |
| `ENTSOE_DAM_DAILY_SYNC_SKIP_IF_COMPLETE` | Default `0` — **always** upsert all configured zones (ES + PL by default) at each run. Set `1` to skip a run when every zone already has 24 hourly rows for the target delivery day (saves API calls). |
| `ENTSOE_DAM_SYNC_HOURS_BRUSSELS` | e.g. `12,13,14,15` |
| `ENTSOE_DAM_DAILY_SYNC_MINUTE_BRUSSELS` | Minute of the hour (default `0`). |
| `ENTSOE_DAM_MANUAL_SYNC_ENABLED` | `1` to allow `POST /api/dam/entsoe/sync` and `POST /api/dam/entsoe/sync-zone`. |

## HTTP endpoints (Open EMS)

- `GET /api/dam/entsoe/zones` — aliases, EICs, time zones.  
- `GET /api/dam/entsoe/chart-day?date=YYYY-MM-DD&zone=ES` (or `zone=PL`) — hourly **EUR/MWh** and **EUR/kWh** from DB.  
- `GET /api/dam/entsoe/chart-day-zones?date=YYYY-MM-DD&zones=ES,PL` — same as above for **multiple** zones in one JSON (`zones.ES`, `zones.PL`, …). Used by the OREE chart overlay.  
  **Lazy backfill:** when `ENTSOE_CHART_DAY_LAZY_FETCH` is enabled (default `true`) and the DB has no rows for that `date` + zone, the server **calls ENTSO-E once**, upserts `entsoe_dam_price`, then returns the same response. Only for delivery days **≤ tomorrow (Europe/Brussels)** (no future day-ahead).  
  `lazySyncTriggered: true` in the JSON when a pull was performed.  
- `POST /api/dam/entsoe/sync?delivery=YYYY-MM-DD` — fetch all configured zones (requires manual sync enabled + token).  
- `POST /api/dam/entsoe/sync-zone?zone=ES&delivery=YYYY-MM-DD` — fetch one zone (`zone=PL`, etc.).

## Database

Table **`entsoe_dam_price`**: `(trade_day, zone_eic, period)` → `price_eur_mwh` for `period` 1..24.

## Daily DB sync (scheduler)

With `ENTSOE_DAM_DAILY_SYNC_ENABLED=1` and `ENTSOE_SECURITY_TOKEN` set, Open EMS runs **`sync_entsoe_all_configured_zones`** at each **Europe/Brussels** time in `ENTSOE_DAM_SYNC_HOURS_BRUSSELS` (default 12–15). The **delivery day** is **tomorrow in Brussels** (`delivery_tomorrow_brussels()`), matching day-ahead publication. All EICs in **`ENTSOE_DAM_ZONE_EICS`** (default **Spain + Poland**) are pulled and upserted into **`entsoe_dam_price`**. With default **`ENTSOE_DAM_DAILY_SYNC_SKIP_IF_COMPLETE=0`**, every window runs a full refresh for ES and PL even if rows already exist.

## Notes

- **Rate limits:** ENTSO-E applies per-token limits; each configured zone is one GET per sync run.  
- **Currency:** Prices are stored as published (typically **EUR/MWh** for these zones).  
- **DST / resolution:** Responses may use hourly or 15-minute points; 15-minute series are averaged to hourly slots 1..24.  
- **IOP:** Test environment uses a different host (`iop-transparency` / Keycloak IOP) — not wired in Open EMS by default; set `ENTSOE_API_BASE_URL` if you need IOP.
