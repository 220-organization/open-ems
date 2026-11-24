# EMS Open API — Run Strategy & Time Schedule Integration Guide (V2.1)


| Item             | Value                                                                          |
| ---------------- | ------------------------------------------------------------------------------ |
| Document version | **V2.1**                                                                       |
| API version      | `v1`                                                                           |
| Service          | **ems-open-api**                                                               |
| Live contract    | [EU Swagger UI](https://eur.ubetter.com.cn/ems-open-api/swagger-ui/index.html) |


---



## 1. Design goals

Third-party integrators typically need to:

1. **Select a run strategy** and set SOC limits, power, and other parameters.
2. **Configure charge/discharge time slots** (multi-segment `slots`: when to charge, discharge, or idle, and at what power).

V2.1 conventions:


| Principle                  | Description                                                                                                                |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| **Per-strategy models**    | Each `strategy` exposes one parameter block (`backup` / `peakValley` / …), not the full database entity.                   |
| **One-shot (recommended)** | `PUT /run-strategy` may include `slots` in the same request so **strategy + schedule** are saved atomically on the server. |
| **Keep time-schedule**     | Use `PUT /time-schedule` when only slots change; use `GET /time-schedule` for **today’s effective** schedule.              |
| **Device-local time**      | All `HH:mm:ss` values are **device local time**; clients do not send timezone.                                             |


---



## 2. Authentication & base URL

This section is the **minimum path** for run-strategy / time-schedule.

Base URL (pick one):


| Region | Base URL                                  |
| ------ | ----------------------------------------- |
| EU     | `https://eur.ubetter.com.cn/ems-open-api` |


All paths below are relative to Base URL (e.g. `POST {Base URL}/v1/auth/token`).

### 2.1 Obtain `accessToken` and `tenantId`


| Item          | Value                         |
| ------------- | ----------------------------- |
| Method / path | `POST /v1/auth/token`         |
| Auth headers  | **Not required** on this call |


**Request body**


| Field          | Required | Description                                                      |
| -------------- | -------- | ---------------------------------------------------------------- |
| username       | Yes      | API user login (granted by operator)                             |
| password       | Yes      | Password                                                         |
| tenantUsername | Yes      | Tenant **root** login name (same as console Open API admin page) |


```http
POST /v1/auth/token
Content-Type: application/json

{
  "username": "220km",
  "password": "your_password",
  "tenantUsername": "220km"
}
```

**Success** (`code=0` in envelope, HTTP 200). Important fields in `data`:


| Field           | Use                                                                                            |
| --------------- | ---------------------------------------------------------------------------------------------- |
| **accessToken** | `Authorization: Bearer {accessToken}` on every business call                                   |
| **tenantId**    | Header `X-Tenant-Id: {tenantId}` — must match login response (internal tenant root account ID) |
| tokenType       | Always `Bearer`                                                                                |
| expiresIn       | Token TTL in seconds; re-login when expired                                                    |
| tenantUsername  | Echo of request; store for your own bookkeeping                                                |


```json
{
  "code": 0,
  "message": "success",
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "tokenType": "Bearer",
    "expiresIn": 7200,
    "tenantId": "1234567890123456789",
    "tenantUsername": "tenant_root"
  },
  "requestId": "..."
}
```



### 2.2 Headers on business APIs (including run-strategy)

```http
Authorization: Bearer {accessToken from data.accessToken}
X-Tenant-Id: {tenantId from data.tenantId}
Content-Type: application/json
X-Request-Id: {optional client trace id}
```

**Swagger UI**: After `POST /v1/auth/token`, click **Authorize** → **bearerAuth** = raw `accessToken` (no `Bearer`  prefix if UI adds it) → **tenantId** = `data.tenantId`. Then call `GET/PUT /v1/devices/{sn}/run-strategy`.

### 2.3 Unified response envelope

Business APIs return HTTP 200 with:

```json
{
  "code": 0,
  "message": "success",
  "data": { },
  "requestId": "...",
  "timestamp": 1730000000000
}
```

`code !== 0` means failure; see `message` and platform error codes. Run-strategy payload lives in `data`.

### 2.4 Quick call chain (run strategy)

1. `POST /v1/auth/token` → save `accessToken`, `tenantId`.
2. `GET /v1/devices?page=1&size=20` → pick device `sn` (master SN).
3. `GET /v1/devices/{sn}/run-strategy` → read current strategy.
4. `PUT /v1/devices/{sn}/run-strategy` → update (optional `slots` for strategy 3 or 7).
5. Optionally `GET /v1/devices/{sn}/time-schedule` for **today’s effective** slots.

---



## 3. Run strategies (1 / 3 / 5 / 6 / 7)



### 3.1 strategy = 1 — Backup (charge only, no grid arbitrage)


| Item                | Description                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------- |
| **Meaning**         | **Backup power**: charge the battery for outage reserve; **not** for discharge-to-grid arbitrage. |
| **Parameter block** | `backup`                                                                                          |
| `slots`             | **Do not send**. PUT with `slots` returns `40001`.                                                |
| **Typical use**     | Residential backup, fill when grid is available.                                                  |




### 3.2 strategy = 3 — Peak shaving / valley filling


| Item                | Description                                                                                     |
| ------------------- | ----------------------------------------------------------------------------------------------- |
| **Meaning**         | Charge in low-price periods, discharge in high-price periods (TOU arbitrage or bill reduction). |
| **Parameter block** | `peakValley`                                                                                    |
| `slots`             | **Strongly recommended** in `PUT run-strategy`; or use `PUT time-schedule` later.               |
| **Typical use**     | C&I two charge / two discharge templates.                                                       |




### 3.3 strategy = 5 — Self-consumption


| Item                | Description                                                                     |
| ------------------- | ------------------------------------------------------------------------------- |
| **Meaning**         | PV serves load first; surplus charges the battery; not primarily TOU arbitrage. |
| **Parameter block** | `selfConsumption`                                                               |
| `slots`             | **Do not send**.                                                                |
| **Typical use**     | Residential PV+storage, higher self-consumption rate.                           |




### 3.4 strategy = 6 — AI auto (economic)


| Item                | Description                                                                                          |
| ------------------- | ---------------------------------------------------------------------------------------------------- |
| **Meaning**         | With AI price fetch enabled, the platform **generates daily** charge/discharge schedules.            |
| **Parameter block** | `aiAuto`                                                                                             |
| `slots`             | **PUT forbidden**; `GET run-strategy` / `GET time-schedule` may **read-only** show today’s AI slots. |
| **Typical use**     | Sites in regions with AI price data.                                                                 |




### 3.5 strategy = 7 — Transformer dynamic expansion


| Item                | Description                                                                                              |
| ------------------- | -------------------------------------------------------------------------------------------------------- |
| **Meaning**         | Discharge at peak load to **ease transformer loading**; charge off-peak; optional multi-segment `slots`. |
| **Parameter block** | `transformerExpand`                                                                                      |
| `slots`             | **Optional** (same structure as strategy 3). Transformer-specific thresholds via `PUT /config`.          |
| **Typical use**     | C&I sites with transformer capacity limits.                                                              |


---



## 4. Integration patterns



### 4.1 Pattern A — Single `PUT run-strategy` (recommended)

Best when **changing strategy and slots together** (strategy **3** or **7**).

```text
PUT /v1/devices/{sn}/run-strategy
  → body: { strategy, peakValley|..., slots?: [...] }
```



### 4.2 Pattern B — Strategy and schedule separate

Best when strategy is fixed and you **only adjust slots**.

```text
PUT /v1/devices/{sn}/time-schedule
  → body: { chargeSoc?, dischargeSoc?, slots }
```



### 4.3 Query


| Goal                                         | API                                                    |
| -------------------------------------------- | ------------------------------------------------------ |
| Current strategy + configured slots (3 / 7)  | `GET /run-strategy` (includes `slots` when applicable) |
| Today’s effective slots (incl. read-only AI) | `GET /time-schedule`                                   |


---



## 5. Shared type: `slots[]`

Same structure for `run-strategy` and `time-schedule`.


| Field             | Type   | Required    | Description                                                                                                                                                |
| ----------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| startTime         | string | Yes         | `HH:mm:ss`, device local                                                                                                                                   |
| endTime           | string | Yes         | `HH:mm:ss`; `00:00:00` means end of day (24:00)                                                                                                            |
| mode              | int    | Yes         | `0` idle, `1` charge, `2` discharge                                                                                                                        |
| power             | number | Recommended | Power (kW); `0` for idle segments                                                                                                                          |
| price             | number | No          | Optional segment price override (CNY/kWh). Omit or `0` = use device tariff; **legacy** storage (`ess_price_time`) omits the field on GET when DB price ≤ 0 |
| chargeSocLimit    | int    | No          | Charge SOC ceiling (%) for this segment                                                                                                                    |
| dischargeSocLimit | int    | No          | Discharge SOC floor (%) for this segment                                                                                                                   |


**Validation:**

- Except when `endTime=00:00:00`, `startTime` must be **before** `endTime`.  
- Segments may **touch**; full 24h coverage is not required; gaps follow device default behavior.  
- For `mode=1/2`, use `power > 0` when possible.

---



## 6. API: `/v1/devices/{sn}/run-strategy`

Requires **§2.2 headers**. Path parameter `sn` = device master serial number (from `GET /v1/devices`).


| Item               | Value                                                                                                                      |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| GET                | `/v1/devices/{sn}/run-strategy`                                                                                            |
| PUT                | `/v1/devices/{sn}/run-strategy`                                                                                            |
| Request body (PUT) | `OpenApiRunStrategyDTO` — `strategy` required; send **one** block matching `strategy`; optional `slots` only for **3 / 7** |
| Success payload    | Same shape in `data` (GET and PUT response)                                                                                |


Writes are audited. After PUT, the service notifies the device (same msg path as console). Partial PUT: omitted fields do not overwrite stored values.

### 6.1 HTTP


| Method | Description                                                                                                                                                             |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | Returns `strategy` and the matching parameter block; for strategy **3 or 7**, includes `slots` (saved template; aligns with `GET time-schedule` when AI is not active). |
| PUT    | Saves strategy; optional `slots` (only for **3 / 7**).                                                                                                                  |




### 6.2 Top-level shape (live response vs Swagger)

**Live GET / PUT bodies** contain `strategy`, **one parameter block** for the current strategy, and (for strategy **3 / 7** only) non-empty `slots`. They do **not** list every nested block at once.

Example (peak–valley, `strategy=3`):

```json
{
  "strategy": 3,
  "peakValley": {
    "chargeSoc": 95,
    "dischargeSoc": 20,
    "chargePower": 50,
    "dischargePower": 50
  },
  "slots": [
    {
      "startTime": "00:00:00",
      "endTime": "08:00:00",
      "mode": 1,
      "power": 50
    }
  ]
}
```


| Field                   | Rules                                                                                     |
| ----------------------- | ----------------------------------------------------------------------------------------- |
| strategy                | **Required** on PUT                                                                       |
| backup / peakValley / … | On **PUT**, send only the block matching `strategy`; **GET** returns only that block      |
| slots                   | **Optional**; writable only for **3, 7**; forbidden for **6**, **1**, **5**               |
| Time fields             | JSON strings `HH:mm:ss` (e.g. `"08:00:00"`), not `{ hour, minute, second, nano }` objects |


> **Swagger UI**: After redeploy, **Models** and **PUT run-strategy / time-schedule** show **curated examples** (one strategy block, `HH:mm:ss` strings). If you still see all blocks at `0`, refresh OpenAPI cache or use **Try it out** response body.

PUT still supports partial updates: omitted fields do not overwrite stored values.

### 6.3 Parameter blocks



#### `backup` — strategy = 1


| Field       | Type   | Description           |
| ----------- | ------ | --------------------- |
| chargeSoc   | int    | Charge cutoff SOC (%) |
| chargePower | number | Charge power (kW)     |




#### `peakValley` — strategy = 3


| Field                | Type   | Description                                    |
| -------------------- | ------ | ---------------------------------------------- |
| chargeSoc            | int    | Charge cutoff SOC (%)                          |
| dischargeSoc         | int    | Discharge cutoff SOC (%)                       |
| chargePower          | number | Default charge power (kW)                      |
| dischargePower       | number | Default discharge power (kW)                   |
| allowChargeInValley  | int    | Allow charge in valley `0/1` (optional)        |
| allowChargeInPeak    | int    | Allow charge in peak `0/1` (optional)          |
| allowDischargeInPeak | int    | Allow discharge in peak `0/1` (optional)       |
| …                    |        | Other sharp/peak/normal/valley flags as needed |


> Most integrators only need **SOC, power, and** `slots`; tariff-period flags are optional.



#### `selfConsumption` — strategy = 5


| Field        | Type | Description             |
| ------------ | ---- | ----------------------- |
| chargeSoc    | int  | Charge SOC limit (%)    |
| dischargeSoc | int  | Discharge SOC limit (%) |




#### `aiAuto` — strategy = 6


| Field          | Type   | Description                |
| -------------- | ------ | -------------------------- |
| chargeSoc      | int    | Charge cutoff SOC (%)      |
| dischargeSoc   | int    | Discharge cutoff SOC (%)   |
| chargePower    | number | Charge power (kW)          |
| dischargePower | number | Discharge power (kW)       |
| aiEnergySource | int    | `0` PV only; `1` PV + grid |




#### `transformerExpand` — strategy = 7


| Field          | Type   | Description              |
| -------------- | ------ | ------------------------ |
| chargeSoc      | int    | Charge cutoff SOC (%)    |
| dischargeSoc   | int    | Discharge cutoff SOC (%) |
| chargePower    | number | Charge power (kW)        |
| dischargePower | number | Discharge power (kW)     |




### 6.4 Server orchestration on PUT (ems-open-api)

In one transaction:

1. Validate `strategy`, parameter block, and `slots` combination.
2. Persist `ess_run_strategy` (and AI-related config, same as console).
3. If `slots` present: same persistence and dispatch as `OpenApiTimeScheduleService` (legacy vs new calendar routed internally).
4. Device commands: strategy change **msgId 18** and **13**; schedule change **msgId 14** (and 15/16 for calendar rules when needed).

**PUT without** `slots`: updates strategy parameters only; **does not delete** existing slots.

---



## 7. API: `/v1/devices/{sn}/time-schedule`

Kept with a minimal model.


| Method | Body                                              | Description                                                                                   |
| ------ | ------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| GET    | —                                                 | `{ chargeSoc?, dischargeSoc?, slots[] }`; read-only AI slots when strategy=6 and AI is active |
| PUT    | `chargeSoc?`, `dischargeSoc?`, `slots` (required) | Updates slots (and optional SOC) only; **does not change** `strategy`                         |


Writes the **same data** as `PUT run-strategy` with `slots`; use one path; avoid concurrent overwrites (serialize calls).

---



## 8. Full examples

Example SN: `UBT0420215200730007`.  
Headers omitted; use `Authorization` and `X-Tenant-Id` in production.

---



### 8.1 Peak shaving — one PUT (strategy + two charge / two discharge)

**Request**

```http
PUT /v1/devices/UBT0420215200730007/run-strategy
Content-Type: application/json
```

```json
{
  "strategy": 3,
  "peakValley": {
    "chargeSoc": 98,
    "dischargeSoc": 10,
    "chargePower": 50,
    "dischargePower": 50
  },
  "slots": [
    {
      "startTime": "00:00:00",
      "endTime": "06:30:00",
      "mode": 1,
      "power": 50,
      "chargeSocLimit": 98
    },
    {
      "startTime": "06:30:00",
      "endTime": "10:00:00",
      "mode": 0,
      "power": 0
    },
    {
      "startTime": "10:00:00",
      "endTime": "12:00:00",
      "mode": 2,
      "power": 50,
      "dischargeSocLimit": 10
    },
    {
      "startTime": "12:00:00",
      "endTime": "14:00:00",
      "mode": 0,
      "power": 0
    },
    {
      "startTime": "14:00:00",
      "endTime": "17:00:00",
      "mode": 2,
      "power": 50,
      "dischargeSocLimit": 10
    },
    {
      "startTime": "17:00:00",
      "endTime": "22:00:00",
      "mode": 0,
      "power": 0
    },
    {
      "startTime": "22:00:00",
      "endTime": "00:00:00",
      "mode": 1,
      "power": 50,
      "chargeSocLimit": 98
    }
  ]
}
```

**Response** `data` **(example)**

```json
{
  "strategy": 3,
  "peakValley": {
    "chargeSoc": 98,
    "dischargeSoc": 10,
    "chargePower": 50,
    "dischargePower": 50
  },
  "slots": [
    { "startTime": "00:00:00", "endTime": "06:30:00", "mode": 1, "power": 50, "chargeSocLimit": 98 },
    { "startTime": "06:30:00", "endTime": "10:00:00", "mode": 0, "power": 0 },
    { "startTime": "10:00:00", "endTime": "12:00:00", "mode": 2, "power": 50, "dischargeSocLimit": 10 },
    { "startTime": "12:00:00", "endTime": "14:00:00", "mode": 0, "power": 0 },
    { "startTime": "14:00:00", "endTime": "17:00:00", "mode": 2, "power": 50, "dischargeSocLimit": 10 },
    { "startTime": "17:00:00", "endTime": "22:00:00", "mode": 0, "power": 0 },
    { "startTime": "22:00:00", "endTime": "00:00:00", "mode": 1, "power": 50, "chargeSocLimit": 98 }
  ]
}
```

**Note:** Night charge 22:00–06:30; discharge 10:00–12:00 and 14:00–17:00; idle otherwise.

---



### 8.2 Peak shaving — slots only (`time-schedule`)

Strategy is already 3; move midday discharge to 11:00–13:00:

```http
PUT /v1/devices/UBT0420215200730007/time-schedule
Content-Type: application/json
```

```json
{
  "chargeSoc": 98,
  "dischargeSoc": 10,
  "slots": [
    { "startTime": "00:00:00", "endTime": "08:00:00", "mode": 1, "power": 50 },
    { "startTime": "08:00:00", "endTime": "11:00:00", "mode": 0, "power": 0 },
    { "startTime": "11:00:00", "endTime": "13:00:00", "mode": 2, "power": 50 },
    { "startTime": "13:00:00", "endTime": "22:00:00", "mode": 0, "power": 0 },
    { "startTime": "22:00:00", "endTime": "00:00:00", "mode": 1, "power": 50 }
  ]
}
```

**Verify with GET**

```http
GET /v1/devices/UBT0420215200730007/time-schedule
```

```json
{
  "code": 0,
  "data": {
    "chargeSoc": 98,
    "dischargeSoc": 10,
    "slots": [ "... same as PUT ..." ]
  }
}
```

---



### 8.3 Backup — strategy only, no `slots`

```http
PUT /v1/devices/ESS-BACKUP-001/run-strategy
```

```json
{
  "strategy": 1,
  "backup": {
    "chargeSoc": 100,
    "chargePower": 20
  }
}
```

**Error example** (with slots):

```json
{
  "strategy": 1,
  "backup": { "chargeSoc": 100 },
  "slots": [ { "startTime": "00:00:00", "endTime": "08:00:00", "mode": 1, "power": 20 } ]
}
```

→ `code: 40001`, `message`: `当前运行策略不支持配置时段` (strategy does not support time slots)

---



### 8.4 Self-consumption

```http
PUT /v1/devices/ESS-PV-002/run-strategy
```

```json
{
  "strategy": 5,
  "selfConsumption": {
    "chargeSoc": 100,
    "dischargeSoc": 15
  }
}
```

---



### 8.5 AI auto — strategy only; schedule read-only

```http
PUT /v1/devices/ESS-AI-BG-003/run-strategy
```

```json
{
  "strategy": 6,
  "aiAuto": {
    "chargeSoc": 95,
    "dischargeSoc": 10,
    "chargePower": 40,
    "dischargePower": 40,
    "aiEnergySource": 1
  }
}
```

**Read today’s AI schedule**

```http
GET /v1/devices/ESS-AI-BG-003/time-schedule
```

```json
{
  "code": 0,
  "data": {
    "chargeSoc": 95,
    "dischargeSoc": 10,
    "slots": [
      { "startTime": "02:00:00", "endTime": "05:30:00", "mode": 1, "power": 40 },
      { "startTime": "18:00:00", "endTime": "21:00:00", "mode": 2, "power": 40 }
    ]
  }
}
```

**Manual AI schedule PUT is rejected**

```http
PUT /v1/devices/ESS-AI-BG-003/time-schedule
{ "slots": [ ... ] }
```

→ `40001`: AI schedule is system-generated and cannot be modified via Open API

---



### 8.6 Transformer expansion — strategy + optional slots

```http
PUT /v1/devices/ESS-TX-004/run-strategy
```

```json
{
  "strategy": 7,
  "transformerExpand": {
    "chargeSoc": 90,
    "dischargeSoc": 20,
    "chargePower": 30,
    "dischargePower": 80
  },
  "slots": [
    { "startTime": "08:00:00", "endTime": "12:00:00", "mode": 2, "power": 80 },
    { "startTime": "12:00:00", "endTime": "14:00:00", "mode": 0, "power": 0 },
    { "startTime": "23:00:00", "endTime": "06:00:00", "mode": 1, "power": 30 }
  ]
}
```

Transformer **charge-stop SOC** and related fields: use `PUT /v1/devices/{sn}/config` (e.g. `transformerDynExpandChargeStopSoc`); see the full integration guide.

---



### 8.7 GET `run-strategy` — peak shaving readback

```http
GET /v1/devices/UBT0420215200730007/run-strategy
```

```json
{
  "code": 0,
  "data": {
    "strategy": 3,
    "peakValley": {
      "chargeSoc": 98,
      "dischargeSoc": 10,
      "chargePower": 50,
      "dischargePower": 50
    },
    "slots": [ "... same as §8.1 ..." ]
  }
}
```

For strategy=1, **no** `slots` **field**:

```json
{
  "strategy": 1,
  "backup": {
    "chargeSoc": 100,
    "chargePower": 20
  }
}
```

---



## 9. Strategy capability matrix


| strategy | Name               | PUT run-strategy block | `slots` on run-strategy | PUT time-schedule  |
| -------- | ------------------ | ---------------------- | ----------------------- | ------------------ |
| 1        | Backup             | `backup`               | No                      | No                 |
| 3        | Peak shaving       | `peakValley`           | **Yes (recommended)**   | Yes                |
| 5        | Self-consumption   | `selfConsumption`      | No                      | No                 |
| 6        | AI auto            | `aiAuto`               | No                      | No (GET read-only) |
| 7        | Transformer expand | `transformerExpand`    | Optional                | Yes                |


---



## 10. Implementation checklist (ems-open-api)


| #   | Item                               | Status / notes                                                                                            |
| --- | ---------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 1   | V2 `OpenApiRunStrategyDTO`         | `strategy` + nested blocks + `List<OpenApiTimeScheduleSlotDTO> slots`                                     |
| 2   | `OpenApiRunStrategyService#update` | When `slots` present: validate strategy ∈ {3,7}, delegate schedule persist + dispatch in same transaction |
| 3   | `OpenApiRunStrategyService#get`    | Attach `slots` for strategy 3/7 (aligned with schedule read logic)                                        |
| 4   | `OpenApiTimeScheduleDTO`           | Public fields: `chargeSoc`, `dischargeSoc`, `slots` only                                                  |
| 5   | Remove flat run-strategy model     | **Done** (V2 nested model)                                                                                |
| 6   | Swagger                            | Nested schemas; `doc_zh` / `doc_en` aligned                                                               |
| 7   | strategy **7**                     | Validation range `0–7`                                                                                    |


---



## 11. Change log


| Date       | Version | Notes                                                                       |
| ---------- | ------- | --------------------------------------------------------------------------- |
| 2026-11-24 | V2.1    | Optional `slots` on `run-strategy`; slim `time-schedule`; expanded examples |
| 2026-11-24 | V2.0    | Initial guide                                                               |


---



## 12. Appendix: other strategies


| strategy | Name                       | Notes                                               |
| -------- | -------------------------- | --------------------------------------------------- |
| 0        | Manual / master control    | `manual` block: `chargeCtrl` 1 charge / 2 discharge |
| 4        | Scheduled charge/discharge | `fixedTime` two windows; no `slots`                 |
| 8 / 9    | Other modes                | Per project and permissions                         |


Full device APIs: [Third-Party API Integration Guide](./Third-Party-API-Integration-Guide.md).