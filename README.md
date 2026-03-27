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

## License

Licensed under the **GNU General Public License v3.0** — see [`LICENSE`](LICENSE).
