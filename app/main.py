import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Note
from app.routers import b2b_proxy, dam, deye_proxy, entsoe_dam, huawei_proxy, nbu_fx, power_flow_totals, server_metrics
from app.schemas import NoteCreate, NoteRead
from app import settings
from app.deye_api import deye_configured, deye_missing_env_names
from app.huawei_api import huawei_configured, huawei_missing_env_names
from app.entsoe_dam_scheduler import entsoe_dam_daily_sync_loop
from app.entsoe_dam_service import entsoe_dam_configured
from app.oree_dam_scheduler import dam_daily_sync_loop
from app.oree_dam_service import oree_dam_configured
from app.deye_soc_scheduler import deye_soc_snapshot_loop
from app.huawei_power_scheduler import huawei_power_snapshot_loop
from app.huawei_station_energy_scheduler import huawei_station_energy_loop
from app.deye_low_dam_charge_scheduler import deye_low_dam_charge_loop
from app.deye_peak_auto_scheduler import deye_peak_auto_discharge_loop
from app.deye_ev_port_scheduler import deye_ev_port_export_loop
from app.rate_limit_middleware import InMemoryIpRateLimiter, PerIpRateLimitMiddleware

BASE_DIR = Path(__file__).resolve().parent.parent
UI_BUILD = BASE_DIR / "ui" / "build"
UI_STATIC = UI_BUILD / "static"
REACT_INDEX = UI_BUILD / "index.html"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Open EMS starting — B2B upstream: %s", settings.B2B_API_BASE_URL)
    if deye_configured():
        logger.info("Deye API: configured (base: %s)", settings.DEYE_API_BASE_URL)
    else:
        missing = deye_missing_env_names()
        logger.warning(
            "Deye API: not configured — set env: %s",
            ", ".join(missing) if missing else "DEYE_APP_ID, DEYE_APP_SECRET, DEYE_EMAIL, DEYE_PASSWORD",
        )
    if oree_dam_configured():
        logger.info("OREE DAM: OREE_API_KEY set (base: %s)", settings.OREE_API_BASE_URL)
    else:
        logger.warning("OREE DAM: not configured — set OREE_API_KEY for DAM sync and chart line")
    if entsoe_dam_configured():
        logger.info("ENTSO-E DAM: ENTSOE_SECURITY_TOKEN set (base: %s)", settings.ENTSOE_API_BASE_URL)
    else:
        logger.warning("ENTSO-E DAM: not configured — set ENTSOE_SECURITY_TOKEN for ES/PL charts (see docs/ENTSOE_TRANSPARENCY_DAM.md)")
    if huawei_configured():
        logger.info("Huawei FusionSolar: configured (base: %s)", settings.HUAWEI_BASE_URL)
    else:
        hm = huawei_missing_env_names()
        logger.warning(
            "Huawei FusionSolar: not configured — set env: %s",
            ", ".join(hm) if hm else "HUAWEI_USER_NAME, HUAWEI_SYSTEM_CODE",
        )

    if settings.RATE_LIMIT_ENABLED:
        logger.info(
            "HTTP rate limit: %s requests / 60s per IP (RATE_LIMIT_*; /health and /static/ excluded)",
            settings.RATE_LIMIT_PER_IP_PER_MINUTE,
        )

    stop_dam_sched: Optional[asyncio.Event] = None
    dam_sched_task: Optional[asyncio.Task[None]] = None
    if settings.OREE_DAM_DAILY_SYNC_ENABLED:
        stop_dam_sched = asyncio.Event()
        dam_sched_task = asyncio.create_task(dam_daily_sync_loop(stop_dam_sched))
        logger.info(
            "OREE DAM: DB sync at Kyiv hours %s:%02d (skip if tomorrow complete; OREE_DAM_SYNC_HOURS_KYIV / disable with OREE_DAM_DAILY_SYNC_ENABLED=0)",
            ",".join(str(h) for h in settings.OREE_DAM_SYNC_HOURS_KYIV),
            settings.OREE_DAM_DAILY_SYNC_MINUTE_KYIV,
        )

    stop_entsoe_sched: Optional[asyncio.Event] = None
    entsoe_sched_task: Optional[asyncio.Task[None]] = None
    if settings.ENTSOE_DAM_DAILY_SYNC_ENABLED:
        stop_entsoe_sched = asyncio.Event()
        entsoe_sched_task = asyncio.create_task(entsoe_dam_daily_sync_loop(stop_entsoe_sched))
        logger.info(
            "ENTSO-E DAM: DB sync at Brussels hours %s:%02d (ENTSOE_DAM_SYNC_HOURS_BRUSSELS / disable with ENTSOE_DAM_DAILY_SYNC_ENABLED=0)",
            ",".join(str(h) for h in settings.ENTSOE_DAM_SYNC_HOURS_BRUSSELS),
            settings.ENTSOE_DAM_DAILY_SYNC_MINUTE_BRUSSELS,
        )

    stop_deye_soc: Optional[asyncio.Event] = None
    deye_soc_task: Optional[asyncio.Task[None]] = None
    if settings.DEYE_SOC_SNAPSHOT_ENABLED:
        stop_deye_soc = asyncio.Event()
        deye_soc_task = asyncio.create_task(deye_soc_snapshot_loop(stop_deye_soc))
        logger.info(
            "Deye SoC: snapshot to DB every %ss (DEYE_SOC_SNAPSHOT_*)",
            settings.DEYE_SOC_SNAPSHOT_INTERVAL_SEC,
        )

    stop_huawei_power: Optional[asyncio.Event] = None
    huawei_power_task: Optional[asyncio.Task[None]] = None
    if settings.HUAWEI_POWER_SNAPSHOT_ENABLED:
        stop_huawei_power = asyncio.Event()
        huawei_power_task = asyncio.create_task(huawei_power_snapshot_loop(stop_huawei_power))
        logger.info(
            "Huawei power: snapshot to DB every %ss (HUAWEI_POWER_SNAPSHOT_*)",
            settings.HUAWEI_POWER_SNAPSHOT_INTERVAL_SEC,
        )

    stop_huawei_station_energy: Optional[asyncio.Event] = None
    huawei_station_energy_task: Optional[asyncio.Task[None]] = None
    if settings.HUAWEI_STATION_ENERGY_SNAPSHOT_ENABLED:
        stop_huawei_station_energy = asyncio.Event()
        huawei_station_energy_task = asyncio.create_task(
            huawei_station_energy_loop(stop_huawei_station_energy)
        )
        logger.info(
            "Huawei station energy: refresh day/month/year totals every %ss (HUAWEI_STATION_ENERGY_SNAPSHOT_*)",
            settings.HUAWEI_STATION_ENERGY_SNAPSHOT_INTERVAL_SEC,
        )

    stop_peak_auto: Optional[asyncio.Event] = None
    peak_auto_task: Optional[asyncio.Task[None]] = None
    if settings.DEYE_PEAK_AUTO_DISCHARGE_SCHEDULER_ENABLED:
        stop_peak_auto = asyncio.Event()
        peak_auto_task = asyncio.create_task(deye_peak_auto_discharge_loop(stop_peak_auto))
        logger.info(
            "Deye peak DAM auto discharge: tick every %ss when DEYE_* is set (DEYE_PEAK_AUTO_DISCHARGE_*)",
            settings.DEYE_PEAK_AUTO_DISCHARGE_INTERVAL_SEC,
        )

    stop_low_dam_charge: Optional[asyncio.Event] = None
    low_dam_charge_task: Optional[asyncio.Task[None]] = None
    if settings.DEYE_LOW_DAM_CHARGE_SCHEDULER_ENABLED:
        stop_low_dam_charge = asyncio.Event()
        low_dam_charge_task = asyncio.create_task(deye_low_dam_charge_loop(stop_low_dam_charge))
        logger.info(
            "Deye low DAM auto charge: tick every %ss when DEYE_* is set (DEYE_LOW_DAM_CHARGE_*)",
            settings.DEYE_LOW_DAM_CHARGE_INTERVAL_SEC,
        )

    stop_ev_port: Optional[asyncio.Event] = None
    ev_port_task: Optional[asyncio.Task[None]] = None
    if deye_configured():
        stop_ev_port = asyncio.Event()
        ev_port_task = asyncio.create_task(deye_ev_port_export_loop(stop_ev_port))
        logger.info(
            "Deye EV port dynamic export: tick every %ss when label contains evport<N> (B2B %s)",
            settings.DEYE_EV_PORT_EXPORT_INTERVAL_SEC,
            settings.B2B_API_BASE_URL,
        )

    yield

    if dam_sched_task is not None and stop_dam_sched is not None:
        stop_dam_sched.set()
        dam_sched_task.cancel()
        try:
            await dam_sched_task
        except asyncio.CancelledError:
            pass
    if entsoe_sched_task is not None and stop_entsoe_sched is not None:
        stop_entsoe_sched.set()
        entsoe_sched_task.cancel()
        try:
            await entsoe_sched_task
        except asyncio.CancelledError:
            pass
    if deye_soc_task is not None and stop_deye_soc is not None:
        stop_deye_soc.set()
        deye_soc_task.cancel()
        try:
            await deye_soc_task
        except asyncio.CancelledError:
            pass
    if huawei_power_task is not None and stop_huawei_power is not None:
        stop_huawei_power.set()
        huawei_power_task.cancel()
        try:
            await huawei_power_task
        except asyncio.CancelledError:
            pass
    if huawei_station_energy_task is not None and stop_huawei_station_energy is not None:
        stop_huawei_station_energy.set()
        huawei_station_energy_task.cancel()
        try:
            await huawei_station_energy_task
        except asyncio.CancelledError:
            pass
    if peak_auto_task is not None and stop_peak_auto is not None:
        stop_peak_auto.set()
        peak_auto_task.cancel()
        try:
            await peak_auto_task
        except asyncio.CancelledError:
            pass
    if low_dam_charge_task is not None and stop_low_dam_charge is not None:
        stop_low_dam_charge.set()
        low_dam_charge_task.cancel()
        try:
            await low_dam_charge_task
        except asyncio.CancelledError:
            pass
    if ev_port_task is not None and stop_ev_port is not None:
        stop_ev_port.set()
        ev_port_task.cancel()
        try:
            await ev_port_task
        except asyncio.CancelledError:
            pass
    logger.info("Open EMS shutting down")


_spa_desc = (
    "Power flow UI (React): [/](/), [/power-flow](/power-flow), [/dam-chart](/dam-chart). API docs: [/docs](/docs)."
    if settings.OPEN_EMS_SERVE_SPA
    else "REST API only — run the CRA dev server for the Power flow UI. API docs: [/docs](/docs)."
)
app = FastAPI(
    title="Open EMS",
    description=_spa_desc,
    lifespan=lifespan,
)

_ip_rate_limiter = InMemoryIpRateLimiter(
    max_hits=settings.RATE_LIMIT_PER_IP_PER_MINUTE,
    window_sec=60.0,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    PerIpRateLimitMiddleware,
    limiter=_ip_rate_limiter,
    enabled=settings.RATE_LIMIT_ENABLED,
)

app.include_router(b2b_proxy.router)
app.include_router(deye_proxy.router)
app.include_router(huawei_proxy.router)
app.include_router(dam.router)
app.include_router(entsoe_dam.router)
app.include_router(nbu_fx.router)
app.include_router(server_metrics.router)
app.include_router(power_flow_totals.router)

# Production / `npm run build`: serve CRA output only (no legacy static HTML).
# Local dev: OPEN_EMS_SERVE_SPA=0 — API only; UI from `npm start`.
if settings.OPEN_EMS_SERVE_SPA:
    _SPA_INDEX_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    if UI_STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=str(UI_STATIC)), name="ui_static")

    def _react_spa_index() -> FileResponse:
        if not REACT_INDEX.is_file():
            raise HTTPException(
                status_code=503,
                detail="React UI not built. Run: cd ui && npm run build",
            )
        return FileResponse(REACT_INDEX, headers=_SPA_INDEX_CACHE)

    @app.get("/", include_in_schema=False)
    async def root() -> FileResponse:
        return _react_spa_index()

    @app.get("/power-flow", include_in_schema=False)
    async def power_flow_page() -> FileResponse:
        return _react_spa_index()

    @app.get("/dam-chart", include_in_schema=False)
    async def dam_chart_page() -> FileResponse:
        return _react_spa_index()
else:

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": "Open EMS API",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/health",
        }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/notes", response_model=list[NoteRead])
async def list_notes(db: AsyncSession = Depends(get_db)) -> list[Note]:
    result = await db.execute(select(Note).order_by(Note.id.desc()))
    return list(result.scalars().all())


@app.post("/notes", response_model=NoteRead)
async def create_note(payload: NoteCreate, db: AsyncSession = Depends(get_db)) -> Note:
    note = Note(title=payload.title, body=payload.body)
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


@app.get("/notes/{note_id}", response_model=NoteRead)
async def get_note(note_id: int, db: AsyncSession = Depends(get_db)) -> Note:
    note = await db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note
