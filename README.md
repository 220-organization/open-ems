# Open EMS

Minimal FastAPI service with SQLite stored on a Docker named volume (same persistence pattern as `admin-bot`).

## Run with Docker

```bash
docker compose up --build
```

- API: http://localhost:8095
- Docs: http://localhost:8095/docs
- Health: `GET /health`
- Example CRUD: `GET/POST /notes`

## Local run (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8090
```

SQLite file defaults to `./data/open_ems.db` relative to the project root.
