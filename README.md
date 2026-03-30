# Open EMS

## Local development

From this directory:

```bash
./run-local.sh
```

The script frees the default dev ports (listeners are killed, including legacy **3090**), starts PostgreSQL (Docker), runs Flyway migrations, then **uvicorn** with **`--reload`** on **9221** and the **React dev server** (Create React App, Fast Refresh) on **9220**. The API does not serve the old HTML/SPA in this mode (`OPEN_EMS_SERVE_SPA=0`). Override ports with `API_PORT=…` and `UI_PORT=…`.

Re-run `./run-local.sh` anytime: old listeners on those ports are killed first, then both dev processes start again.

Optional: copy `ui/.env.example` → `ui/.env` only if you need overrides; otherwise `run-local.sh` sets `REACT_APP_API_BASE_URL=http://127.0.0.1:9221`.

Local production-style bundle: `cd ui && npm run build` (optional sanity check).

**Docker Compose (server):** builds **`web`** from `Dockerfile.ui` (CRA production build + **nginx** on container port 80 → host **9220**) and **`api`** from `Dockerfile` (FastAPI on host **9221**, `OPEN_EMS_SERVE_SPA=0`). Nginx proxies **`/api/*`** to `api:8090`, so the UI image is built with an empty **`REACT_APP_API_BASE_URL`** by default (same-origin `/api` on port 9220). Override at build time via Compose env **`REACT_APP_API_BASE_URL`** if you need a direct API URL instead.

| What | URL |
|------|-----|
| Power flow UI (React dev) | [http://localhost:9220/](http://localhost:9220/) (`./run-local.sh`) |
| DAM chart (React dev) | [http://localhost:9220/dam-chart](http://localhost:9220/dam-chart) |
| REST API (local dev) | [http://localhost:9221/](http://localhost:9221/) (JSON index; Swagger at `/docs`) |
| OpenAPI (Swagger UI) | [http://localhost:9221/docs](http://localhost:9221/docs) |
| Health | `GET http://localhost:9221/health` |
| Docker: Power flow UI (prod) | host **9220** → `web` (nginx + static React) |
| Docker: REST API (prod) | host **9221** → `api` (Swagger `/docs`, `/health`) |

**Public Power flow (UI):** [https://220-km.com:9220/](https://220-km.com:9220/) — **API / docs:** port **9221** on the same host.

Default DB connection is `postgresql+asyncpg://openems:openems@127.0.0.1:5433/openems` (override with `DATABASE_URL`).

The API loads **`open-ems/.env`** automatically (`python-dotenv`), so `DEYE_*`, `B2B_API_BASE_URL`, `OREE_*`, etc. apply without `export` in the shell. Do not commit real secrets; keep `.env` local (gitignored).

### DAM chart (OREE → DB)

The **`/dam-chart`** page and **`GET /api/dam/chart-day`** use only the **`oree_dam_price`** table (Flyway **`V2__oree_dam_price.sql`**). The UI defaults to **today (Europe/Kiev)** and keeps the trade day in the query string as **`?date=YYYY-MM-DD`**. With no **`date`** query, the API defaults to **today (Kyiv)** as well. Prices come from OREE via **`POST /api/dam/sync`**, a **daily background job at 13:00 Europe/Kiev** (configurable), and a **one-time OREE pull** when the user selects **tomorrow’s date (Kyiv)** and the DB has no DAM rows for that day.

| Variable | Description |
|----------|-------------|
| `OREE_API_KEY` | OREE API key header **`X-API-KEY`** (required for sync and on-demand fetch) |
| `OREE_API_BASE_URL` | Optional. Default `https://api.oree.com.ua/index.php/api` |
| `OREE_API_DAM_PRICES_PATH` | Optional. Default `/damprices` |
| `OREE_COMPARE_ZONE_EIC` | Optional. Default `10Y1001C--000182` (UA IPS integration zone) |
| `OREE_DAM_DAILY_SYNC_ENABLED` | Optional. Default `true` — set `0` / `false` to disable the daily scheduler |
| `OREE_DAM_DAILY_SYNC_HOUR_KYIV` | Optional. Default `13` (0–23, Europe/Kiev wall time) |
| `OREE_DAM_DAILY_SYNC_MINUTE_KYIV` | Optional. Default `0` (0–59) |

**SoC and grid on the DAM chart:** With an inverter selected on the Power flow page (`?inverter=<serial>`) or on **`/dam-chart?inverter=<serial>`**, the UI requests **`GET /api/deye/soc-history-day`** and draws **mean battery SoC % per Europe/Kyiv clock hour** (24 points, same *hour* axis as DAM) on a **right Y-axis**, plus **mean grid power per hour** (signed **W** from Deye: **positive = import**, **negative = export**) as a **bar chart under the main X-axis** (kW in the UI). Rows are stored in **`deye_soc_sample`** (Flyway **`V3`** + **`V4__deye_soc_sample_grid.sql`**): the API process snapshots **all** inverters from **`listWithDevice`** every **`DEYE_SOC_SNAPSHOT_INTERVAL_SEC`** (default **300**), using a **fresh** Deye `device/latest` call (not the UI’s in-memory SoC TTL).

### Deye inverter list (Power flow)

The header **Inverter ID** dropdown loads inverters from the **Deye Cloud Open API** (`POST /v1.0/station/listWithDevice`), i.e. plants/devices tied to the same account as the web [plant list](https://www.deyecloud.com/business/maintain/plant). Configure via environment variables (see `.env.example`):

| Variable | Description |
|----------|-------------|
| `DEYE_APP_ID` | App ID from [developer.deyecloud.com/app](https://developer.deyecloud.com/app) |
| `DEYE_APP_SECRET` | App secret from the same portal |
| `DEYE_EMAIL` | Deye Cloud account email (login) |
| `DEYE_PASSWORD` | Deye Cloud account password (plain in env; the server sends **SHA-256** to `POST /account/token`, same pattern as the Java `DeyeAuth` client) |
| `DEYE_COMPANY_ID` | Usually `0` for a personal account; for a business member account, use the company id from Deye (e.g. `/account/info` in the Open API docs) |
| `DEYE_API_BASE_URL` | Optional. Default `https://eu1-developer.deyecloud.com/v1.0` (EU). Use the US base URL if your developer account is on the US data center. |
| `DEYE_SOC_SNAPSHOT_ENABLED` | Optional. Default `true` — background task writes SoC to **`deye_soc_sample`**; set `0` / `false` to disable |
| `DEYE_SOC_SNAPSHOT_INTERVAL_SEC` | Optional. Default `300` (min `60`, max `3600`) — seconds between DB snapshots |

UI calls `GET /api/deye/inverters` (JSON: `configured`, `items[]` with `deviceSn` and `label`), `POST /api/deye/inverter-socs` with body `{"deviceSns":["…"]}` for SoC in the dropdown (batched Deye `POST /device/latest`, **5-minute in-memory TTL cache** on the server), and optionally `GET /api/deye/soc?deviceSn=<serial>` (same SoC source, uses the same cache). With an inverter selected, it polls `GET /api/deye/ess-power?deviceSn=<serial>` about every **20s** (same Deye `device/latest` response, **~25s** server cache): **`batteryPowerW`** signed (**positive = discharging**, **negative = charging**) for the Battery tile and ESS flow; **`loadPowerW`** (non-negative, home/AC load) for the **Load** tile and its flow only—no B2B consumption there. If a metric is missing in `dataList`, that tile uses `—` or simulated ESS for battery only. SoC parser matches the Java `DynamicPriceService` idea (`SOC` / `BMS_SOC` / `BATTERY_SOC`). Do not commit real credentials.

**Postman:** import `postman/Deye_OpenAPI_Inverters.postman_collection.json` (optional: `postman/Deye_OpenAPI_Inverters.postman_environment.json`). Run request **1** then **2**; request **3** hits the local Open EMS proxy. Set `app_id`, `app_secret`, `deye_email`, `deye_password_plain` (plain password — the pre-request script computes SHA-256).

## Deploy (GitHub Actions + SSH)

Workflow `.github/workflows/deploy.yml` in **this repository** runs on push to `main`, `master`, or `preprod`: packs the tree (excluding `.git` / `.venv`), copies it over SSH, then runs `docker compose` on the server.

**Target OS (tested):** **Ubuntu 24.04.4 LTS** (Noble Numbat), x86_64 — same line as `docker.io` / `docker-compose-v2` from Ubuntu archives. On the server, print the exact image:

```bash
lsb_release -a
```

```bash
cat /etc/os-release
```

Example lines you should see on that host include `VERSION="24.04.4 LTS (Noble Numbat)"` and `VERSION_ID="24.04"`.

Deployment path on the server: `/220/open-ems`. The workflow connects as **`root`** on port **22**; the SSH target host is read from the repository secret **`DEPLOY_HOST`** (same pattern as **`PRIVATE_KEY`**).

**Repository secrets for the API container** (written to `/220/open-ems/.env` on each deploy — same names as local `.env`):

| Secret | Purpose |
|--------|---------|
| `B2B_API_BASE_URL` | Upstream B2B proxy (optional; default in compose if unset) |
| `DEYE_API_BASE_URL` | Deye Open API base (optional; EU default if unset) |
| `DEYE_APP_ID` | Developer portal app id |
| `DEYE_APP_SECRET` | App secret |
| `DEYE_EMAIL` | Deye account email |
| `DEYE_PASSWORD` | Plain login password (app hashes SHA-256 for token) |
| `DEYE_COMPANY_ID` | Optional; defaults to `0` if secret missing |
| `OREE_API_KEY` | OREE DAM API key for `POST /api/dam/sync` and DAM line on `/dam-chart` (optional) |
| `OREE_API_BASE_URL` | Optional OREE base URL (workflow default matches `docker-compose`) |
| `OREE_API_DAM_PRICES_PATH` | Optional path (default `/damprices`) |
| `OREE_COMPARE_ZONE_EIC` | Optional bidding zone EIC (default UA IPS integration) |

Without the `DEYE_*` secrets, the inverter dropdown stays empty on the server even if it works locally. Without **`OREE_API_KEY`**, DAM prices are not synced and the chart DAM line stays empty unless rows were loaded elsewhere.

### 1. Generate SSH key pair (on your laptop or admin machine)

Use **Ed25519**, empty passphrase (typical for CI), and a dedicated key file:

```bash
mkdir -p ~/.ssh/open-ems-deploy
ssh-keygen -t ed25519 \
  -f ~/.ssh/open-ems-deploy/open_ems_deploy_ed25519 \
  -N "" \
  -C "open-ems-github-actions-deploy"
```

This creates:

- **Private key:** `~/.ssh/open-ems-deploy/open_ems_deploy_ed25519` — for GitHub only (never commit).
- **Public key:** `~/.ssh/open-ems-deploy/open_ems_deploy_ed25519.pub` — for the Ubuntu server.

Show the public key (one line) to copy:

```bash
cat ~/.ssh/open-ems-deploy/open_ems_deploy_ed25519.pub
```

### 2. Add deploy secrets to GitHub (repository Actions secrets)

The workflow reads **`secrets.PRIVATE_KEY`** and **`secrets.DEPLOY_HOST`**. Add both under **Settings** → **Secrets and variables** → **Actions** → **Secrets** → **New repository secret** (not Variables, unless you change the workflow to use them).

#### `PRIVATE_KEY`

The **entire** private key file, including header/footer:

```bash
cat ~/.ssh/open-ems-deploy/open_ems_deploy_ed25519
```

You must include:

- `-----BEGIN OPENSSH PRIVATE KEY-----`
- all lines in between
- `-----END OPENSSH PRIVATE KEY-----`

#### `DEPLOY_HOST`

SSH hostname or IP of the deploy target only (no `root@`, no port). Example: `65.108.212.26`.

*(Optional: if you use **Environments** with protection rules, you can instead define **`PRIVATE_KEY`** and **`DEPLOY_HOST`** as environment secrets and add `environment: …` to the job in `deploy.yml` — the default workflow expects **repository** secrets.)*

### 3. Add the public key to Ubuntu (`authorized_keys`)

SSH into the server as the same user GitHub Actions uses (here **`root`**), then:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
```

Append the **public** key line (replace the placeholder with your real `.pub` line):

```bash
echo 'ssh-ed25519 AAAA...your-public-key... open-ems-github-actions-deploy' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Or from your admin machine (if password SSH is still enabled once):

```bash
ssh-copy-id -i ~/.ssh/open-ems-deploy/open_ems_deploy_ed25519.pub root@YOUR_SERVER_IP
```

Test login with the **private** key only (no password):

```bash
ssh -i ~/.ssh/open-ems-deploy/open_ems_deploy_ed25519 -o IdentitiesOnly=yes root@YOUR_SERVER_IP 'echo ok'
```

### 4. What the workflow does on the server

- Ensures **Docker** and **`docker compose` v2** (installs `docker.io` / `docker-compose-v2` on Ubuntu if missing).
- Syncs the repo tarball and runs `docker compose down --remove-orphans` then `docker compose up -d --build` under `/220/open-ems`.

Optional: set `RUN_FLYWAY_ON_START=true` and `DATABASE_URL` in the API service environment if you run the app image against an external database (Flyway runs at container start via `scripts/render_flyway_migrate.py`). The default Compose stack uses the bundled `db` service and does not need those variables for migrations (Flyway runs as the `migrate` service).

- Health check: `GET http://<host>:9221/health` (API service)
- Published ports on the host: **`9220`** → `web` (nginx + React), **`9221`** → `api` (FastAPI) — see `docker-compose.yml`.
