from pathlib import Path

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

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_POWER_FLOW = BASE_DIR / "static" / "power_flow"

app = FastAPI(
    title="Open EMS",
    description="Power flow UI: [/](/) and [/power-flow](/power-flow). API docs: [/docs](/docs).",
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

if STATIC_POWER_FLOW.is_dir():
    app.mount(
        "/static/power-flow",
        StaticFiles(directory=str(STATIC_POWER_FLOW)),
        name="power_flow_static",
    )


def _power_flow_file_response() -> FileResponse:
    index = STATIC_POWER_FLOW / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Power flow UI not found")
    return FileResponse(index)


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return _power_flow_file_response()


@app.get("/power-flow", include_in_schema=False)
async def power_flow_page() -> FileResponse:
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
