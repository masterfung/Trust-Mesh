"""Async SQLite database setup with SQLAlchemy."""

import os

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Configurable DB path — each pod gets its own database
DB_PATH = os.getenv("TRUSTMESH_DB", "./trustmesh.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    """Set SQLite PRAGMAs for performance and safety.

    WAL mode prevents "database is locked" during concurrent cross-pod queries.
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA secure_delete=ON")
    cursor.close()


async def get_db() -> AsyncSession:
    """FastAPI dependency for database sessions."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


def _migrate_network_expires_at(conn):
    """Add expires_at column to networks table if missing."""
    from sqlalchemy import text
    result = conn.execute(text("PRAGMA table_info(networks)"))
    columns = {row[1] for row in result}
    if "expires_at" not in columns:
        conn.execute(text("ALTER TABLE networks ADD COLUMN expires_at DATETIME"))


def _migrate_capsule_versions(conn):
    """Add deleted_at column to knowledge_capsules and create capsule_versions/ucan_revocations tables."""
    from sqlalchemy import text
    # Add deleted_at to knowledge_capsules if missing
    result = conn.execute(text("PRAGMA table_info(knowledge_capsules)"))
    columns = {row[1] for row in result}
    if "deleted_at" not in columns:
        conn.execute(text("ALTER TABLE knowledge_capsules ADD COLUMN deleted_at DATETIME"))

    # Create capsule_versions table if missing
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS capsule_versions (
            id VARCHAR(36) PRIMARY KEY,
            capsule_id VARCHAR(36) NOT NULL,
            version_number INTEGER NOT NULL,
            changed_by VARCHAR(36) NOT NULL,
            changed_fields TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # Create ucan_revocations table if missing
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS ucan_revocations (
            id VARCHAR(36) PRIMARY KEY,
            token_hash VARCHAR(64) UNIQUE NOT NULL,
            revoked_by VARCHAR(36) NOT NULL,
            reason TEXT,
            revoked_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # Add audit log indexes for performance (table may not exist during test setup)
    try:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_target_user ON audit_logs(target_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_logs(event_type)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs(created_at DESC)"))
    except Exception:
        pass  # Indexes are an optimization — safe to skip if table not yet created


def _migrate_user_email_avatar(conn):
    """Add email and avatar_url columns to users table if missing."""
    from sqlalchemy import text
    result = conn.execute(text("PRAGMA table_info(users)"))
    columns = {row[1] for row in result}
    if "email" not in columns:
        conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(254)"))
        try:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL"))
        except Exception:
            pass  # Partial indexes may not be supported in older SQLite
    if "avatar_url" not in columns:
        conn.execute(text("ALTER TABLE users ADD COLUMN avatar_url TEXT"))


async def init_db():
    """Create all tables and run migrations."""
    from src.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_network_expires_at)
        await conn.run_sync(_migrate_capsule_versions)
        await conn.run_sync(_migrate_user_email_avatar)


async def drop_db():
    """Drop all tables (for testing/reset)."""
    from src.models import Base

    # Close FTS handle first — it holds a Zig-side SQLite connection to the same DB.
    try:
        from src.embeddings import close_fts
        close_fts()
    except Exception:
        pass

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
