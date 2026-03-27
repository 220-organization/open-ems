import os
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base

# Persistent path inside Docker volume (see admin-bot SUPPORT_DB_PATH pattern)
_default_dir = Path(__file__).resolve().parent.parent / "data"
_db_file = os.environ.get("OPEN_EMS_DB_PATH", str(_default_dir / "open_ems.db"))
_db_path = Path(_db_file)
_db_path.parent.mkdir(parents=True, exist_ok=True)

# SQLite async URL: absolute path needs four slashes after scheme
_sqlite_url = f"sqlite+aiosqlite:///{_db_path.as_posix()}"

engine = create_async_engine(_sqlite_url, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
