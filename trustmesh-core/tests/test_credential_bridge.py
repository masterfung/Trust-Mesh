"""Tests for credential bridge — ctypes wrappers for agent tools."""

import os
import sqlite3

import pytest
import pytest_asyncio

from src.database import init_db, drop_db, engine


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Set up a fresh DB with credential tables for each test.

    Clears Zig-managed tables (vault_secrets, credential_shares, credential_audit)
    between tests via raw sqlite3. Does NOT delete the DB file to avoid leaving
    stale Zig pointers for subsequent test files.
    """
    from src.embeddings import close_fts, init_fts
    from src import credential_bridge, transit_bridge

    # Close stale FTS handle if any, then reinit everything fresh
    close_fts()
    await drop_db()
    await init_db()
    init_fts()
    transit_bridge._ensure_init()
    # Reset credential_bridge cached DB handle so it picks up the fresh one
    credential_bridge._db_handle = None
    credential_bridge._initialized = False
    credential_bridge._ensure_zig()

    # Flush the SQLAlchemy connection pool so the raw sqlite3 DELETE below can
    # acquire a write lock without hitting WAL contention from pooled connections.
    await engine.dispose()

    # Clear Zig-managed credential tables (not in SQLAlchemy metadata)
    db_path = os.getenv("TRUSTMESH_DB", "./trustmesh.db")
    conn = sqlite3.connect(db_path)
    for table in ("vault_secrets", "credential_shares", "credential_audit"):
        try:
            conn.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            pass  # Table may not exist yet
    conn.commit()
    conn.close()

    yield
    # Cleanup: reset credential bridge state but leave DB + FTS valid
    credential_bridge._db_handle = None
    credential_bridge._initialized = False
    # Reset trust.py cached handle so it picks up fresh one
    from src.trust import reset_db_handle
    reset_db_handle()


def _setup_vault_key(user_id="cred-test-user"):
    """Store a vault key for the test user so encrypt/decrypt works."""
    from src import transit_bridge
    key = os.urandom(32)
    transit_bridge.store_key(user_id, key)
    return user_id


@pytest.mark.asyncio
async def test_create_credential():
    """Create a credential and get back an ID."""
    from src.credential_bridge import create_credential
    uid = _setup_vault_key()
    cred_id = create_credential(
        owner_id=uid,
        name="GitHub Token",
        service="github",
        secret="ghp_test12345678901234567890",
        scoped_tools=["web_search"],
        category="dev",
    )
    assert isinstance(cred_id, str)
    assert len(cred_id) == 32


@pytest.mark.asyncio
async def test_list_credentials():
    """List credentials returns metadata (no secrets)."""
    from src.credential_bridge import create_credential, list_credentials
    uid = _setup_vault_key()
    create_credential(uid, "Test Cred", "testservice", "secret123", ["tool_a"])

    creds = list_credentials(uid)
    assert len(creds) == 1
    cred = creds[0]
    assert "name" in cred
    assert cred["name"] == "Test Cred"
    # Secret should NOT be in metadata list
    assert "secret" not in cred


@pytest.mark.asyncio
async def test_list_credentials_empty():
    """List for user with no credentials returns empty."""
    from src.credential_bridge import list_credentials
    _setup_vault_key("empty-user")
    creds = list_credentials("empty-user")
    assert creds == []


@pytest.mark.asyncio
async def test_deactivate_credential():
    """Deactivate a credential."""
    from src.credential_bridge import create_credential, deactivate_credential, list_credentials
    uid = _setup_vault_key()
    cred_id = create_credential(uid, "To Delete", "svc", "secret", ["tool"])

    deactivate_credential(cred_id, uid)

    # Should no longer appear in active list
    creds = list_credentials(uid)
    active = [c for c in creds if c.get("is_active", True)]
    deactivated = [c for c in creds if not c.get("is_active", True)]
    assert len(active) == 0 or len(deactivated) >= 1


@pytest.mark.asyncio
async def test_credential_for_tool():
    """Get credentials scoped to a specific tool."""
    from src.credential_bridge import create_credential, get_credential_for_tool
    uid = _setup_vault_key()
    create_credential(uid, "API Key", "openai", "sk-test123", ["chat_tool", "completion"])

    creds = get_credential_for_tool(uid, "chat_tool")
    assert len(creds) >= 1


@pytest.mark.asyncio
async def test_credential_for_unmatched_tool():
    """Tool not in scoped_tools returns empty."""
    from src.credential_bridge import create_credential, get_credential_for_tool
    uid = _setup_vault_key()
    create_credential(uid, "Scoped", "svc", "secret", ["tool_a"])

    creds = get_credential_for_tool(uid, "tool_b")
    assert len(creds) == 0


@pytest.mark.asyncio
async def test_record_use():
    """Record use doesn't raise."""
    from src.credential_bridge import create_credential, record_use
    uid = _setup_vault_key()
    cred_id = create_credential(uid, "Use Test", "svc", "secret", ["tool"])

    # Should not raise
    record_use(cred_id, uid, "tool")


@pytest.mark.asyncio
async def test_deactivate_wrong_owner():
    """Deactivate by wrong owner raises."""
    from src.credential_bridge import create_credential, deactivate_credential
    uid = _setup_vault_key()
    cred_id = create_credential(uid, "Protected", "svc", "secret", ["tool"])

    _setup_vault_key("other-user")
    with pytest.raises((PermissionError, RuntimeError)):
        deactivate_credential(cred_id, "other-user")


@pytest.mark.asyncio
async def test_create_multiple_credentials():
    """Multiple credentials for same user."""
    from src.credential_bridge import create_credential, list_credentials
    uid = _setup_vault_key()
    create_credential(uid, "Cred A", "svc_a", "secret_a", ["tool_a"])
    create_credential(uid, "Cred B", "svc_b", "secret_b", ["tool_b"])
    create_credential(uid, "Cred C", "svc_c", "secret_c", ["tool_c"])

    creds = list_credentials(uid)
    assert len(creds) == 3


@pytest.mark.asyncio
async def test_init_tables_idempotent():
    """init_tables can be called multiple times without error."""
    from src.credential_bridge import init_tables
    init_tables()
    init_tables()  # Should not raise
