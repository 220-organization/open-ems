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
from app.routers import b2b_proxy, deye_proxy
from app.schemas import NoteCreate, NoteRead
from app import settings
from app.deye_api import deye_configured, deye_missing_env_names

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_POWER_FLOW = BASE_DIR / "static" / "power_flow"
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
    yield
    logger.info("Open EMS shutting down")


app = FastAPI(
    title="Open EMS",
    description="Power flow UI: [/](/) and [/power-flow](/power-flow). API docs: [/docs](/docs).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(b2b_proxy.router)
app.include_router(deye_proxy.router)

# Production / `npm run build`: CRA emits assets under build/static/ (includes power-flow images from public/).
if UI_STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(UI_STATIC)), name="ui_static")
elif STATIC_POWER_FLOW.is_dir():
    app.mount(
        "/static/power-flow",
        StaticFiles(directory=str(STATIC_POWER_FLOW)),
        name="power_flow_static",
    )


def _react_spa_index() -> Optional[FileResponse]:
    if REACT_INDEX.is_file():
        return FileResponse(REACT_INDEX)
    return None


def _power_flow_file_response() -> FileResponse:
    index = STATIC_POWER_FLOW / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Power flow UI not found")
    return FileResponse(index)


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    spa = _react_spa_index()
    if spa is not None:
        return spa
    return _power_flow_file_response()


@app.get("/power-flow", include_in_schema=False)
async def power_flow_page() -> FileResponse:
    spa = _react_spa_index()
    if spa is not None:
        return spa
    return _power_flow_file_response()


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
