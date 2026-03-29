import os
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _normalize_async_database_url(url: str) -> str:
    """Hosts may use postgresql://; SQLAlchemy async needs postgresql+asyncpg://."""
    if "+asyncpg" in url.split("://", 1)[0]:
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


# Async URL for SQLAlchemy; Flyway applies schema via JDBC (see docker-compose / Render).
_raw_db = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://openems:openems@localhost:5432/openems",
)
DATABASE_URL = _normalize_async_database_url(_raw_db)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
