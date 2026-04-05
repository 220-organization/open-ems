# Open EMS

**Production UI:** [https://220-km.com:9220/](https://220-km.com:9220/)

## Run locally

From the `open-ems` directory:

```bash
./run-local.sh
```

Requires **Docker** (Compose v2) and **Node.js** for the UI dev server. The script starts PostgreSQL, runs Flyway migrations, then:

- **UI:** [http://localhost:9220/](http://localhost:9220/) (React dev server)
- **API:** [http://localhost:9221/](http://localhost:9221/) (Swagger: `/docs`, health: `/health`)

Optional: `UI_PORT` / `API_PORT` env vars; copy `ui/.env.example` → `ui/.env` only if you need overrides.

The API reads **`open-ems/.env`** via `python-dotenv` (see [Environment variables](#environment-variables)).

## Run with Docker

From `open-ems`:

1. Copy `.env.example` → `.env` and set at least **Deye** and **OREE** variables (see below).
2. Start the stack:

```bash
docker compose up -d --build
```

- **UI:** host port **9220** → nginx + production React build  
- **API:** host port **9221**  
- **PostgreSQL:** host port **5433** (user/db/password `openems` / `openems` / `openems`)

`docker compose` loads `.env` from this directory for variable substitution into the `api` service.

## Deploy on Ubuntu

**Requirements:** Ubuntu 22.04+ (or similar) with **Docker** and **Docker Compose v2**:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
```

Copy the project to the server (e.g. `git clone` or `scp`), then:

```bash
cd /path/to/open-ems
cp .env.example .env
# edit .env — see below
docker compose up -d --build
```

Open **9220** / **9221** in the host firewall if you need remote access.

### Optional: GitHub Actions deploy

Workflow: `.github/workflows/deploy.yml` (push to `main`, `master`, or `preprod`). It SSHs as **`root`** to **`secrets.DEPLOY_HOST`** (Ubuntu **IP or hostname**, no `root@` prefix) using **`secrets.PRIVATE_KEY`** (full Ed25519 private key PEM). It writes app secrets into **`/220/open-ems/.env`** on the server. Adjust the path in the workflow if you use a different directory.

**SSH key (one-time):** generate a deploy key, add the **public** key to `~/.ssh/authorized_keys` on the server, store the **private** key in GitHub as `PRIVATE_KEY`.

## Environment variables

### On the Ubuntu server (`.env` next to `docker-compose.yml`)

| Variable | Required for | Notes |
|----------|----------------|-------|
| `DEYE_APP_ID` | Inverter list, power flow, Deye-backed features | From [developer.deyecloud.com/app](https://developer.deyecloud.com/app) |
| `DEYE_APP_SECRET` | Same | App secret from the same portal |
| `DEYE_EMAIL` | Same | Deye Cloud login email |
| `DEYE_PASSWORD` | Same | Plain password; the API hashes it for Deye token requests |
| `DEYE_COMPANY_ID` | Business accounts | Often `0` for personal accounts |
| `OREE_API_KEY` | DAM price sync & chart data in DB | Header `X-API-KEY` for OREE API (Ukraine **UA** line) |
| `ENTSOE_SECURITY_TOKEN` | ES / PL EUR overlay on DAM chart | [Transparency Platform](https://transparency.entsoe.eu/) REST token; see `docs/ENTSOE_TRANSPARENCY_DAM.md` |

Optional: `DEYE_API_BASE_URL`, `DATABASE_URL` (only if not using the bundled `db` service), `B2B_API_BASE_URL`, `ENTSOE_API_BASE_URL`, `ENTSOE_DAM_ZONE_EICS`, and other keys documented in `.env.example`.

### For CI / SSH deploy (GitHub Actions secrets)

| Secret | Purpose |
|--------|---------|
| `DEPLOY_HOST` | Ubuntu server **IP or DNS name** (SSH target) |
| `PRIVATE_KEY` | **Private** SSH key (full file including `BEGIN` / `END` lines) for `root` (or match your workflow user) |

Additional repository secrets (same names as in `.env`) are copied into the server `.env` by the deploy workflow — at minimum set **`DEYE_APP_ID`**, **`DEYE_APP_SECRET`**, **`DEYE_EMAIL`**, **`DEYE_PASSWORD`**, and **`OREE_API_KEY`** there if you deploy via Actions. For ENTSO-E DAM (chart overlays always include **ES/PL/UA** in code), add **`ENTSOE_SECURITY_TOKEN`** (and optionally **`ENTSOE_API_BASE_URL`**; **`ENTSOE_DAM_ZONE_EICS`** only if you need **additional** zones beyond those three). Without **`ENTSOE_SECURITY_TOKEN`** in secrets, each deploy overwrites the server `.env` and the API container will not receive the token (Compose passes env into `api`; there is no `.env` file inside the image).

Do not commit real `.env` files; keep secrets on the server and in GitHub **Secrets** only.
