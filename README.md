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

Brings up `db`, runs Flyway, then **uvicorn --reload**. After the API responds, your **default browser opens Swagger UI** (`/docs`). Default HTTP port is **9220** (avoids conflicts with services often bound to **8090**). Next free port is used if that one is busy. Override:

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
uvicorn app.main:app --reload --port 9220
```

See `.env.example` for the default URL shape.

## Deploy (GitHub Actions + SSH)

Workflow `.github/workflows/deploy.yml` in **this repository** runs on push to `main`, `master`, or `preprod`: packs the tree (excluding `.git` / `.venv`), copies it over SSH, then runs `docker compose` on the server.

- **Host**: `65.108.212.26`, deployment path: `/220/open-ems`
- **Secret**: GitHub Actions secret `PRIVATE_KEY` (SSH private key for `root` on that host)
- On the server: `docker compose down --remove-orphans` then `docker compose up -d --build` (PostgreSQL + Flyway migrate + API as in `docker-compose.yml`).

Optional: set `RUN_FLYWAY_ON_START=true` and `DATABASE_URL` in the API service environment if you run the app image against an external database (Flyway runs at container start via `scripts/render_flyway_migrate.py`). The default Compose stack uses the bundled `db` service and does not need those variables for migrations (Flyway runs as the `migrate` service).

- Health check: `GET /health`
- Published API port on the host: `8095` → container `8090` (see `docker-compose.yml`).

## License

Licensed under the **GNU General Public License v3.0** — see [`LICENSE`](LICENSE).
