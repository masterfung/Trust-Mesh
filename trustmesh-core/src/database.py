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


def _migrate_performance_indexes(conn):
    """Add composite indexes for high-traffic query paths."""
    from sqlalchemy import text
    indexes = [
        # Capsule lookups — most frequent query (vault page, agent search)
        "CREATE INDEX IF NOT EXISTS idx_capsules_owner_type ON knowledge_capsules(owner_id, capsule_type)",
        "CREATE INDEX IF NOT EXISTS idx_capsules_owner_deleted ON knowledge_capsules(owner_id, deleted_at)",
        # Connection lookups — both sides of the bidirectional relationship
        "CREATE INDEX IF NOT EXISTS idx_conn_from_status ON connections(from_user_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_conn_to_status ON connections(to_user_id, status)",
        # Connection requests — inbox queries
        "CREATE INDEX IF NOT EXISTS idx_conn_req_to_status ON connection_requests(to_user_id, status)",
        # Network membership — user's networks + network member list
        "CREATE INDEX IF NOT EXISTS idx_netmem_user ON network_memberships(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_netmem_network ON network_memberships(network_id)",
        # Notifications — unread count + inbox listing
        "CREATE INDEX IF NOT EXISTS idx_notif_user_read ON notifications(user_id, read_at)",
    ]
    for ddl in indexes:
        try:
            conn.execute(text(ddl))
        except Exception:
            pass  # Safe to skip — index already exists or table not yet created


def _migrate_user_org_fields(conn):
    """Add org_subtype and agent_mode columns to users table if missing."""
    from sqlalchemy import text
    result = conn.execute(text("PRAGMA table_info(users)"))
    cols = {row[1] for row in result}
    if "org_subtype" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN org_subtype VARCHAR(20)"))
    if "agent_mode" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN agent_mode VARCHAR(20) NOT NULL DEFAULT 'private'"))
        conn.execute(text(
            "UPDATE users SET agent_mode='internal' WHERE user_type IN ('organization','government')"
        ))


def _migrate_connection_request_context(conn):
    """Add context column to connection_requests table if missing."""
    from sqlalchemy import text
    result = conn.execute(text("PRAGMA table_info(connection_requests)"))
    cols = {row[1] for row in result}
    if "context" not in cols:
        conn.execute(text(
            "ALTER TABLE connection_requests ADD COLUMN context VARCHAR(20) NOT NULL DEFAULT 'personal'"
        ))


def _migrate_channel_tokens(conn) -> None:
    """Ensure channel_tokens table exists (defensive — create_all covers fresh DBs)."""
    from sqlalchemy import text
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS channel_tokens (
            id VARCHAR(36) PRIMARY KEY,
            owner_id VARCHAR(36) NOT NULL REFERENCES users(id),
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            name VARCHAR(100) NOT NULL,
            relationship_type VARCHAR(50),
            scopes VARCHAR(200) NOT NULL DEFAULT 'query,memory',
            created_at DATETIME NOT NULL,
            last_used_at DATETIME,
            revoked_at DATETIME
        )
    """))


def _migrate_capsule_propagation(conn):
    """Add propagation column to knowledge_capsules if missing."""
    from sqlalchemy import text
    result = conn.execute(text("PRAGMA table_info(knowledge_capsules)"))
    columns = {row[1] for row in result}
    if "propagation" not in columns:
        conn.execute(text(
            "ALTER TABLE knowledge_capsules ADD COLUMN propagation VARCHAR(20) NOT NULL DEFAULT 'silent'"
        ))


async def init_db():
    """Create all tables and run migrations."""
    # Import all models explicitly so Base.metadata is fully populated
    from src import models as _all_models  # noqa: F401
    from src.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_network_expires_at)
        await conn.run_sync(_migrate_capsule_versions)
        await conn.run_sync(_migrate_user_email_avatar)
        await conn.run_sync(_migrate_user_org_fields)
        await conn.run_sync(_migrate_connection_request_context)
        await conn.run_sync(_migrate_performance_indexes)
        await conn.run_sync(_migrate_channel_tokens)
        await conn.run_sync(_migrate_capsule_propagation)


def _drop_zig_tables(conn) -> None:
    """Remove Zig-managed tables not in SQLAlchemy metadata.

    Uses PRAGMA writable_schema to bypass FTS5 vtable constructor failures
    that occur when FTS5 shadow tables are corrupt (e.g. after an unclean shutdown).
    Also drops timeline / credential / message tables created by libpodos.
    """
    from sqlalchemy import text

    # Bypass vtable destructor for FTS5 tables — safe even on corrupt shadow tables
    conn.execute(text("PRAGMA writable_schema=ON"))
    conn.execute(text(
        "DELETE FROM sqlite_master "
        "WHERE name LIKE 'capsule_fts%' OR name LIKE 'credential_fts%' "
        "OR name LIKE 'message_fts%'"
    ))
    conn.execute(text("PRAGMA writable_schema=OFF"))

    # Drop regular Zig-owned tables (timeline, vault_secrets, credentials, messages)
    for table in (
        "timeline_entries", "timeline_inbox", "timeline_outbox", "timeline_transitions",
        "vault_secrets", "credential_ops", "credential_shares",
        "messages",
    ):
        try:
            conn.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
        except Exception:
            pass  # Best-effort — ignore errors on cleanup


async def drop_db():
    """Drop all tables (for testing/reset)."""
    import sqlite3 as _sqlite3
    from src.models import Base

    # Close FTS handle first — it holds a Zig-side SQLite connection to the same DB.
    try:
        from src.embeddings import close_fts
        close_fts()
    except Exception:
        pass

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        # Also clean up Zig-managed tables (FTS5 vtables + timeline + credentials)
        await conn.run_sync(_drop_zig_tables)

    # Dispose async engine pool so raw sqlite3 can acquire the write lock.
    await engine.dispose()

    # VACUUM compacts orphaned FTS5 shadow-table pages left after the
    # writable_schema deletions above.  Must run outside any transaction.
    try:
        raw = _sqlite3.connect(DB_PATH, timeout=10)
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("VACUUM")
        raw.close()
    except Exception:
        pass
