"""Async SQLite database setup with SQLAlchemy."""

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Configurable DB path — each pod gets its own database
DB_PATH = os.getenv("TRUSTMESH_DB", "./trustmesh.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI dependency for database sessions."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create all tables."""
    from src.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db():
    """Drop all tables (for testing/reset)."""
    from src.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
