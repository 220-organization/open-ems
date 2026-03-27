from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Note
from app.schemas import NoteCreate, NoteRead

app = FastAPI(title="Open EMS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
