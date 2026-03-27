import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Async URL for SQLAlchemy; Flyway applies schema via JDBC (see docker-compose).
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://openems:openems@localhost:5432/openems",
)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
