# Open EMS

[![Deploy](https://github.com/220-organization/open-ems/actions/workflows/deploy.yml/badge.svg)](https://github.com/220-organization/open-ems/actions/workflows/deploy.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/react-18-61dafb.svg)](https://react.dev/)

**Open EMS** is an open-source **Energy Management System** for solar + battery + EV charging installations. It monitors real-time power flow, optimises battery charging against day-ahead electricity market (DAM) prices, and integrates with EV charging networks — all from a single self-hosted dashboard.

**Live demo:** [https://220-km.com:9220/](https://220-km.com:9220/)
**GitHub:** [https://github.com/220-organization/open-ems](https://github.com/220-organization/open-ems)

---

## Features

| Area | Capabilities |
|------|-------------|
| **Power flow** | Real-time Deye inverter telemetry — grid, solar PV, battery SoC, load, EV port |
| **DAM pricing** | Day-ahead market prices from OREE (Ukraine UA) and ENTSO-E (ES, PL) with chart overlays |
| **Smart charging** | Auto-schedule battery charge during cheap DAM hours; low-price threshold triggers |
| **Peak management** | Automated peak-shaving export; peak hour detection and discharge scheduling |
| **Battery SoC control** | Remote SoC target and discharge/charge commands via Deye Cloud API |
| **ROI analytics** | Capital expenditure payback calculator with NBU FX rate integration |
| **Solar forecast** | Open-Meteo solar irradiance forecast integration |
| **EV charging integration** | B2B charging session data via 220-km.com public API |
| **Multi-language UI** | English 🇬🇧, Ukrainian 🇺🇦, Polish 🇵🇱 |
| **Self-hosted** | Single `docker compose up` — PostgreSQL + FastAPI + React; no cloud lock-in |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 React UI (port 9220)            │
│  Power Flow · DAM Chart · ROI · Server Metrics  │
└────────────────────┬────────────────────────────┘
                     │ REST / SSE
┌────────────────────▼────────────────────────────┐
│          FastAPI backend (port 9221)            │
│  Deye Cloud API · OREE DAM · ENTSO-E · NBU FX  │
│  Schedulers: SoC · Peak · DAM · Solar forecast  │
└────────────────────┬────────────────────────────┘
                     │ asyncpg
┌────────────────────▼────────────────────────────┐
│           PostgreSQL 16 (port 5433)             │
│  DAM prices · power samples · ROI · EV sessions │
└─────────────────────────────────────────────────┘
```

**Tech stack:**
- **Backend:** Python 3.11+, FastAPI, asyncpg, APScheduler, httpx
- **Frontend:** React 18, Recharts, Framer Motion, i18n (en/uk/pl)
- **Database:** PostgreSQL 16 with Flyway migrations
- **Infra:** Docker Compose, nginx, GitHub Actions CI/CD

---

## Quick start

### Option 1 — Local development

```bash
git clone https://github.com/220-organization/open-ems.git
cd open-ems
./run-local.sh
```

Requires **Docker** (Compose v2) and **Node.js 20+**. Opens:
- **UI:** [http://localhost:9220/](http://localhost:9220/)
- **API + Swagger:** [http://localhost:9221/docs](http://localhost:9221/docs)

### Option 2 — Docker (production)

```bash
cp .env.example .env
# Fill in Deye and OREE credentials (see Environment variables below)
docker compose up -d --build
```

- UI served by nginx on **port 9220**
- API on **port 9221**
- PostgreSQL on **port 5433** (user/db/password: `openems`)

### Option 3 — Ubuntu server deploy

```bash
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
git clone https://github.com/220-organization/open-ems.git /opt/open-ems
cd /opt/open-ems && cp .env.example .env
# Edit .env, then:
docker compose up -d --build
```

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DEYE_APP_ID` | Yes | App ID from [developer.deyecloud.com](https://developer.deyecloud.com/app) |
| `DEYE_APP_SECRET` | Yes | App secret from the same portal |
| `DEYE_EMAIL` | Yes | Deye Cloud account email |
| `DEYE_PASSWORD` | Yes | Deye Cloud account password (hashed before sending) |
| `DEYE_COMPANY_ID` | No | Usually `0` for personal accounts |
| `OREE_API_KEY` | Yes | OREE API key for Ukraine UA day-ahead prices |
| `ENTSOE_SECURITY_TOKEN` | No | ENTSO-E Transparency Platform token for ES/PL DAM overlays |
| `B2B_API_BASE_URL` | No | Base URL for 220-km.com B2B EV charging API |
| `DATABASE_URL` | No | Override if using an external PostgreSQL |

Copy `.env.example` → `.env` and fill required values. Never commit `.env`.

---

## CI/CD — GitHub Actions

Push to `main`, `master`, or `preprod` triggers the deploy workflow (`.github/workflows/deploy.yml`):

1. Validates UI lockfile (`npm ci`)
2. Packages sources (excluding `.git`)
3. SSHs to `secrets.DEPLOY_HOST` as root and runs `docker compose up --build -d`

**Required GitHub Secrets:**

| Secret | Value |
|--------|-------|
| `DEPLOY_HOST` | Server IP or hostname |
| `PRIVATE_KEY` | Ed25519 private key (full PEM) for SSH |
| `DEYE_APP_ID`, `DEYE_APP_SECRET`, `DEYE_EMAIL`, `DEYE_PASSWORD` | Deye credentials |
| `OREE_API_KEY` | OREE API key |
| `ENTSOE_SECURITY_TOKEN` | (optional) ENTSO-E token |

---

## API reference

Interactive Swagger UI is available at `/docs` when the API is running:
[http://localhost:9221/docs](http://localhost:9221/docs)

Key endpoints:

| Endpoint | Description |
|----------|-------------|
| `GET /power-flow` | Live power flow snapshot (grid, solar, battery, load, EV) |
| `GET /dam/prices` | Day-ahead market prices for configured zones |
| `GET /dam/chart` | DAM chart data with ENTSO-E overlays |
| `GET /roi` | ROI / payback calculator data |
| `POST /deye/soc` | Set battery SoC target remotely |
| `GET /health` | Health check |

---

## Contributing

Pull requests are welcome! Open an issue first for significant changes.

```bash
# Run tests
cd open-ems
python -m pytest tests/
```

Areas where contributions are especially valuable:
- Additional inverter integrations (SolarEdge, Fronius, SMA, Growatt)
- New DAM price sources (EPEX Spot, NordPool, PJM)
- V2G / bidirectional charging support
- Improved solar forecast models

---

## Use cases

- **Solar + battery home/business** — monitor and optimise a Deye hybrid inverter installation
- **EV charging operators** — correlate charging load with DAM prices and battery state
- **Energy researchers** — explore grid-edge DER orchestration with real market signals
- **Open-source energy stack** — self-host an EMS without proprietary cloud lock-in

---

## Related projects

- **220-km.com** — Ukraine EV charging network ([220-km.com](https://220-km.com))
- **OCPP server** — open charge point protocol implementation
- **OCPI microservice** — interoperability layer for roaming networks

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).

Built and maintained by the [220-km.com](https://220-km.com) team in Ukraine.
