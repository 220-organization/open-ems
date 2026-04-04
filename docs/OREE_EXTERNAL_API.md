# OREE external REST API (reference)

This document summarizes the **Market Operator (AT «Оператор ринку»)** public REST JSON API for day-ahead market (DAM) data. It is aligned with the official interface description (including the **test** environment endpoints). Open EMS uses the same contract; implementation details are in [Open EMS integration](#open-ems-integration).

---

## 1. General

- **Protocol:** HTTP, synchronous request/response.
- **Format:** JSON (`Accept: application/json`).
- **Style:** REST-style resources; responses are JSON bodies as described per endpoint.

### Test environment (example base paths)

| Endpoint | Description |
|----------|-------------|
| `https://api-test.oree.com.ua/index.php/api/damprices` | Hourly DAM prices (D+1 auction results). |
| `https://api-test.oree.com.ua/index.php/api/damindexes` | DAM price **indices** (bands such as DAY / NIGHT / PEAK, etc.). |

Production hosts typically use `api.oree.com.ua` (without `-test`). The specification also shows examples with `www.oree.com.ua` as `Host`; the path under `/index.php/api/` is what matters for the API.

### Test `curl` examples (operator test host)

Export your B2B key (do not commit it to git):

```bash
export OREE_API_KEY='your-api-key-here'
```

**DAMPRICES** — hourly auction prices (JSON array):

```bash
curl -sS --location 'https://api-test.oree.com.ua/index.php/api/damprices' \
  --header 'Accept: application/json' \
  --header "X-API-KEY: ${OREE_API_KEY}" \
  --header 'User-Agent: OpenEMS/1.0 (OREE B2B API)'
```

**DAMINDEXES** — indices, **no query** (many clients use this; Open EMS upstream uses the same):

```bash
curl -sS --location 'https://api-test.oree.com.ua/index.php/api/damindexes' \
  --header 'Accept: application/json' \
  --header "X-API-KEY: ${OREE_API_KEY}" \
  --header 'User-Agent: OpenEMS/1.0 (OREE B2B API)'
```

**DAMINDEXES** — optional query `date` in **`DD.MM.YYYY`** (per operator specification):

```bash
curl -sS --location 'https://api-test.oree.com.ua/index.php/api/damindexes?date=05.12.2023' \
  --header 'Accept: application/json' \
  --header "X-API-KEY: ${OREE_API_KEY}" \
  --header 'User-Agent: OpenEMS/1.0 (OREE B2B API)'
```

To hit **production** instead of test, replace the host with `https://api.oree.com.ua` (paths unchanged). Pipe through `jq` if installed: `| jq .`

---

## 2. Authentication

- **Header:** `X-API-KEY: <API key>`  
  The key is issued through the operator’s normal registration process.

- **Failure cases** (from specification): if the key is missing, not registered, or the requested data are not available for the requested period, the service may respond with:

```http
HTTP/1.1 403 Forbidden
Content-Length: 0
```

**Note:** Some B2B keys are scoped so that **`/damprices` succeeds** while **`/damindexes` returns 403** — treat indices as optional if your key only covers hourly prices.

### Example request (conceptual)

```http
GET https://api-test.oree.com.ua/index.php/api/damprices HTTP/1.1
Host: api-test.oree.com.ua
Accept: application/json
X-API-KEY: <your-api-key>
User-Agent: <client identifier>
```

---

## 3. DAMPRICES (`/damprices`)

**Purpose:** Return DAM **hourly prices** for the relevant trade day (auction **D+1** in the specification narrative).

**Success:** `200 OK`, `Content-Type: application/json; charset=UTF-8`

**Body:** A **JSON array** of objects (one object per zone). Typical fields:

| Field | Description |
|-------|-------------|
| `zone_eic` | Trading zone EIC, e.g. `10YUA-WEPS-----0` (Burshtyn TPP energy island), `10Y1001C--000182` (IPS of Ukraine). |
| `trade_day` | Trade day as `YYYY-MM-DD`. |
| `data` | Array of hourly points. |
| `data[].period` | Trading period `1`–`24` (or `23` / `25` when DST shifts apply). |
| `data[].price` | Price for that period (string in examples; **UAH/MWh** in operator materials). |

**Empty result:** HTTP `200` with body:

```json
[]
```

**Example fragment (structure only):**

```json
[
  {
    "zone_eic": "10YUA-WEPS-----0",
    "trade_day": "2020-12-22",
    "data": [
      {"period": "1", "price": "959.12"},
      {"period": "2", "price": "959.12"}
    ]
  }
]
```

---

## 4. DAMINDEXES (`/damindexes`)

**Purpose:** Return **index** values (aggregated band prices vs. previous period, etc.) for a calendar context described by the request.

### Request parameters (per specification)

| Parameter | Description |
|-----------|-------------|
| `date` | Date in **`DD.MM.YYYY`** format (query parameter). |

The specification text also refers to the response as structured index data; the **successful example** below is a **JSON object** whose top-level keys are **zone codes** (e.g. `IND`), not a top-level array.

**Success:** `200 OK`, JSON body.

**Shape (illustrative — zone `IND`):**

| Field / path | Description |
|--------------|-------------|
| `<zone>.trade_day` | Date as `DD.MM.YYYY` (string). |
| `<zone>.DAY` / `NIGHT` / `PEAK` / `HPEAK` / … | Objects with `price` and `percent` (string; decimal comma in examples). |
| `price` | Index level (UAH/MWh in operator examples). |
| `percent` | Change vs. previous value (string, may use comma as decimal separator). |

**Example (abbreviated):**

```json
{
  "IND": {
    "trade_day": "12.12.2023",
    "DAY": { "price": "5548.44", "percent": "-6,29" },
    "NIGHT": { "price": "1466.63", "percent": "-31,76" },
    "PEAK": { "price": "4132.50", "percent": "-20,91" },
    "HPEAK": { "price": "6020.42", "percent": "-2,15" }
  }
}
```

**Empty / no data (example from specification):**

```json
{"IND": []}
```

---

## Open EMS integration

Configuration (see `app/settings.py` and `.env.example`):

| Variable | Role |
|----------|------|
| `OREE_API_BASE_URL` | Base URL including `/index.php/api` (no trailing slash), e.g. production `https://api.oree.com.ua/index.php/api` or test `https://api-test.oree.com.ua/index.php/api`. |
| `OREE_API_DAM_PRICES_PATH` | Default `/damprices`. |
| `OREE_API_DAM_INDEXES_PATH` | Default `/damindexes`. |
| `OREE_API_KEY` | Value for `X-API-KEY`. |
| `OREE_HTTP_USER_AGENT` | Optional; some deployments are sensitive to default HTTP client user agents. |

**Implementation notes:**

- **DAM hourly prices** are stored in `oree_dam_price` and exposed via `GET /api/dam/chart-day` (DB-first; optional lazy OREE sync depending on settings).
- **Indices** are stored in `oree_dam_index` when OREE returns a parseable body. The UI/API layer may call OREE **only for Kyiv “tomorrow”** for on-demand index fetch; other calendar days are **database-only** — see `ensure_dam_indexes_for_day` in `app/oree_dam_service.py`.
- **403 on `/damindexes`:** handled gracefully (indices optional); **hourly `/damprices` sync is not blocked** when indices are forbidden for the same key. `sync_dam_prices_to_db` **commits `oree_dam_price` first**, then runs indices in a follow-up transaction so index errors never roll back prices.
- **Tests:** Live HTTP checks live in `tests/test_oree_api_live.py` (`/damprices` required; `/damindexes` may be skipped if the key returns 403).

---

## Source

This file is a practical condensation of the operator document *«Специфікація зовнішнього АРІ інтерфейсу АТ «Оператор ринку» (тестове середовище)»* (sections on general description, identification, DAMPRICES, DAMINDEXES). Refer to the official PDF/HTML from the operator for authoritative wording and updates.
