"""Data lifecycle management — automatic archival and expiry enforcement."""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from src.database import async_session
from src.models import KnowledgeCapsule, Network

logger = logging.getLogger(__name__)

_lifecycle_task: asyncio.Task | None = None


async def lifecycle_tick():
    """Run one lifecycle maintenance pass."""
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        # 1. Archive expired capsules (expires_at < now, not already archived)
        expired_result = await db.execute(
            select(KnowledgeCapsule).where(
                KnowledgeCapsule.expires_at != None,  # noqa: E711
                KnowledgeCapsule.expires_at < now,
                KnowledgeCapsule.is_archived == False,  # noqa: E712
                KnowledgeCapsule.deleted_at == None,  # noqa: E711
            )
        )
        expired_capsules = expired_result.scalars().all()
        for cap in expired_capsules:
            cap.is_archived = True
            logger.info(f"Auto-archived expired capsule {cap.id} (expired {cap.expires_at})")

        # 2. Auto-archive by age (auto_archive_days field)
        from datetime import timedelta
        age_result = await db.execute(
            select(KnowledgeCapsule).where(
                KnowledgeCapsule.auto_archive_days != None,  # noqa: E711
                KnowledgeCapsule.is_archived == False,  # noqa: E712
                KnowledgeCapsule.deleted_at == None,  # noqa: E711
            )
        )
        for cap in age_result.scalars().all():
            if cap.auto_archive_days and cap.created_at:
                archive_after = cap.created_at + timedelta(days=cap.auto_archive_days)
                if now > archive_after.replace(tzinfo=timezone.utc) if archive_after.tzinfo is None else archive_after:
                    cap.is_archived = True
                    logger.info(f"Auto-archived capsule {cap.id} (age > {cap.auto_archive_days} days)")

        # 3. Mark expired networks
        net_result = await db.execute(
            select(Network).where(
                Network.expires_at != None,  # noqa: E711
                Network.expires_at < now,
            )
        )
        # Note: We don't delete expired networks, just log for now.
        # Network expiry affects pool membership which is handled in trust resolution.
        for net in net_result.scalars().all():
            logger.info(f"Network {net.id} ({net.name}) has expired (expired {net.expires_at})")

        await db.commit()


async def start_lifecycle_loop():
    """Start the background lifecycle loop (runs every 15 minutes)."""
    global _lifecycle_task

    async def _loop():
        while True:
            try:
                await lifecycle_tick()
            except Exception as e:
                logger.error(f"Lifecycle tick error: {e}")
            await asyncio.sleep(900)  # 15 minutes

    _lifecycle_task = asyncio.create_task(_loop())
    logger.info("Lifecycle loop started (15-minute interval)")


async def stop_lifecycle_loop():
    """Stop the background lifecycle loop."""
    global _lifecycle_task
    if _lifecycle_task:
        _lifecycle_task.cancel()
        try:
            await _lifecycle_task
        except asyncio.CancelledError:
            pass
        _lifecycle_task = None
        logger.info("Lifecycle loop stopped")
