"""Tests for data lifecycle management — auto-archival and expiry."""

import asyncio
from datetime import datetime, timedelta, timezone
import pytest
import pytest_asyncio

from src.database import init_db, drop_db, async_session
from src.models import KnowledgeCapsule, User


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await drop_db()
    await init_db()
    yield
    await drop_db()


async def _create_user(username="lifecycle_user"):
    """Create a test user directly in the DB."""
    async with async_session() as db:
        user = User(
            username=username,
            display_name="Lifecycle Test",
            bio="test",
            user_type="person",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def _create_capsule(owner_id, **overrides):
    """Create a test capsule with optional overrides."""
    defaults = {
        "owner_id": owner_id,
        "capsule_type": "note",
        "title": "Test Capsule",
        "content_encrypted": b"encrypted-placeholder",
        "visibility": "private",
        "is_archived": False,
    }
    defaults.update(overrides)
    async with async_session() as db:
        cap = KnowledgeCapsule(**defaults)
        db.add(cap)
        await db.commit()
        await db.refresh(cap)
        return cap.id


@pytest.mark.asyncio
async def test_archives_expired_capsules():
    """Capsules past expires_at should be archived."""
    from src.lifecycle import lifecycle_tick

    uid = await _create_user()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    cap_id = await _create_capsule(uid, expires_at=past)

    await lifecycle_tick()

    async with async_session() as db:
        cap = await db.get(KnowledgeCapsule, cap_id)
        assert cap.is_archived is True


@pytest.mark.asyncio
async def test_does_not_archive_future_expiry():
    """Capsules with future expires_at should NOT be archived."""
    from src.lifecycle import lifecycle_tick

    uid = await _create_user()
    future = datetime.now(timezone.utc) + timedelta(days=30)
    cap_id = await _create_capsule(uid, expires_at=future)

    await lifecycle_tick()

    async with async_session() as db:
        cap = await db.get(KnowledgeCapsule, cap_id)
        assert cap.is_archived is False


@pytest.mark.asyncio
async def test_archives_capsules_past_auto_archive_days():
    """Capsules older than auto_archive_days should be archived."""
    from src.lifecycle import lifecycle_tick

    uid = await _create_user()
    old_date = datetime.now(timezone.utc) - timedelta(days=100)
    cap_id = await _create_capsule(
        uid,
        auto_archive_days=30,
        created_at=old_date,
    )

    await lifecycle_tick()

    async with async_session() as db:
        cap = await db.get(KnowledgeCapsule, cap_id)
        assert cap.is_archived is True


@pytest.mark.asyncio
async def test_does_not_archive_young_capsule_with_auto_archive():
    """Capsule within auto_archive_days threshold stays active."""
    from src.lifecycle import lifecycle_tick

    uid = await _create_user()
    recent = datetime.now(timezone.utc) - timedelta(days=5)
    cap_id = await _create_capsule(
        uid,
        auto_archive_days=30,
        created_at=recent,
    )

    await lifecycle_tick()

    async with async_session() as db:
        cap = await db.get(KnowledgeCapsule, cap_id)
        assert cap.is_archived is False


@pytest.mark.asyncio
async def test_skips_already_archived():
    """Already-archived capsules should not be processed again."""
    from src.lifecycle import lifecycle_tick

    uid = await _create_user()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    cap_id = await _create_capsule(uid, expires_at=past, is_archived=True)

    # Should not raise or fail
    await lifecycle_tick()

    async with async_session() as db:
        cap = await db.get(KnowledgeCapsule, cap_id)
        assert cap.is_archived is True


@pytest.mark.asyncio
async def test_skips_deleted_capsules():
    """Soft-deleted capsules (deleted_at set) should not be archived."""
    from src.lifecycle import lifecycle_tick

    uid = await _create_user()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    cap_id = await _create_capsule(
        uid,
        expires_at=past,
        deleted_at=datetime.now(timezone.utc),
    )

    await lifecycle_tick()

    async with async_session() as db:
        cap = await db.get(KnowledgeCapsule, cap_id)
        # Should remain not archived — deleted capsules are skipped
        assert cap.is_archived is False


@pytest.mark.asyncio
async def test_multiple_capsules_independent():
    """Error in one capsule shouldn't prevent others from archiving."""
    from src.lifecycle import lifecycle_tick

    uid = await _create_user()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    cap1_id = await _create_capsule(uid, expires_at=past, title="Capsule 1")
    cap2_id = await _create_capsule(uid, expires_at=past, title="Capsule 2")

    await lifecycle_tick()

    async with async_session() as db:
        cap1 = await db.get(KnowledgeCapsule, cap1_id)
        cap2 = await db.get(KnowledgeCapsule, cap2_id)
        assert cap1.is_archived is True
        assert cap2.is_archived is True


@pytest.mark.asyncio
async def test_lifecycle_loop_start_stop():
    """Lifecycle loop starts and can be stopped cleanly."""
    from src.lifecycle import start_lifecycle_loop, stop_lifecycle_loop, _lifecycle_task

    await start_lifecycle_loop()
    # Give it a moment to start
    await asyncio.sleep(0.05)

    from src.lifecycle import _lifecycle_task
    assert _lifecycle_task is not None

    await stop_lifecycle_loop()
    from src.lifecycle import _lifecycle_task as task_after
    assert task_after is None
