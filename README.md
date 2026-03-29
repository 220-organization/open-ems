# Open EMS

FastAPI service with **PostgreSQL** and **Flyway** for schema migrations, following the same conventions as the Java backend (`db/migration/postgres/common`, versioned scripts `V{version}__description.sql`).

## Run with Docker

```bash
docker compose up --build
```

Startup order: **PostgreSQL** → **Flyway migrate** (one-shot) → **API**.

- API: http://localhost:8095
- PostgreSQL (host): `localhost:5433` (user/password/db: `openems` / `openems` / `openems`)
- Docs: http://localhost:8095/docs

## Power flow (B2B-style graph)

Interactive flow diagram similar to [220-km.com/b2b?graphView=1](https://220-km.com/b2b?graphView=1): live data from **`GET /b2b/public/realtime-power`** and **`GET /b2b/public/miner-power`** on 220-km.com, proxied server-side as **`/api/b2b/realtime-power`** and **`/api/b2b/miner-power`** (no browser CORS issues).

- UI: http://localhost:8095/power-flow (optional query `?station=655` to filter by station)
- Override upstream base URL: `B2B_API_BASE_URL` (default `https://220-km.com:8080`, same host/port as the main Java API behind the React app)

## Migrations

Add new SQL files under `db/migration/postgres/common/`, e.g. `V2__add_example.sql` (same naming as the Java backend: `V{version}__description.sql`).

Apply migrations using the Compose Flyway image (starts `db` if needed):

```bash
docker compose up -d db
docker compose run --rm migrate
```

## Local API (without rebuilding the API image)

### `./run-local.sh`

Brings up `db`, runs Flyway, then **uvicorn --reload**. After the API responds, your **default browser opens Swagger UI** (`/docs`). Default HTTP port is **8096** (avoids conflicts with services often bound to **8090**). Next free port is used if that one is busy. Override:

```bash
PORT=8090 ./run-local.sh
```

### Manual

Requires PostgreSQL reachable at `DATABASE_URL` and migrations already applied.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://openems:openems@localhost:5433/openems
uvicorn app.main:app --reload --port 8096
```

See `.env.example` for the default URL shape.

## Deploy on Render

Use a [Render Blueprint](https://render.com/docs/infrastructure-as-code) (`render.yaml` in the repo root).

1. Push this repository to GitHub (e.g. [220-organization/open-ems](https://github.com/220-organization/open-ems)).
2. In the [Render Dashboard](https://dashboard.render.com/), choose **New** → **Blueprint**, connect the repo, and apply `render.yaml`.
3. Render provisions **Render Postgres** (`open-ems-db`) and a **Docker** web service (`open-ems`) with `DATABASE_URL` wired from the database.

The web image runs **Flyway** on container start when `RUN_FLYWAY_ON_START=true` (set in the blueprint). This works on the free web tier; [pre-deploy commands](https://render.com/docs/deploys#pre-deploy-command) are paid-only on Render, so migrations are not configured via `preDeployCommand`.

- Health check: `GET /health`
- HTTP port: Render sets `PORT`; the entrypoint binds Uvicorn to that port.
- Optional: set `B2B_API_BASE_URL` in the service **Environment** tab if the upstream API base changes.

## License

Licensed under the **GNU General Public License v3.0** — see [`LICENSE`](LICENSE).
