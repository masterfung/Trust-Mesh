"""Tests for database configuration — SQLite PRAGMA settings."""

import pytest
import pytest_asyncio

from src.database import engine


@pytest.mark.asyncio
async def test_sqlite_wal_mode():
    """Verify WAL journal mode is set."""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql("PRAGMA journal_mode")
        mode = result.scalar()
        assert mode == "wal"


@pytest.mark.asyncio
async def test_sqlite_busy_timeout():
    """Verify busy_timeout is set to 5000ms."""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql("PRAGMA busy_timeout")
        timeout = result.scalar()
        assert timeout == 5000


@pytest.mark.asyncio
async def test_sqlite_secure_delete():
    """Verify secure_delete is ON."""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql("PRAGMA secure_delete")
        sd = result.scalar()
        assert sd == 1
