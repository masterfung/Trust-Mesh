"""Notification routes — activity feed for users."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db, async_session
from src.models import Notification
from src.schemas import NotificationResponse

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/users/{user_id}/notifications", response_model=list[NotificationResponse])
async def list_notifications(user_id: str, db: AsyncSession = Depends(get_db)):
    """List notifications for a user. Unread first, then by recency."""
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.is_read.asc(), Notification.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()


@router.get("/users/{user_id}/notifications/unread-count")
async def unread_count(user_id: str, db: AsyncSession = Depends(get_db)):
    """Get unread notification count (for badge)."""
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
    )
    count = result.scalar() or 0
    return {"count": count}


@router.put("/notifications/{notification_id}/read")
async def mark_read(notification_id: str, db: AsyncSession = Depends(get_db)):
    """Mark a notification as read."""
    notification = await db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(404, "Notification not found")
    notification.is_read = True
    await db.commit()
    return {"ok": True}


@router.put("/users/{user_id}/notifications/read-all")
async def mark_all_read(user_id: str, db: AsyncSession = Depends(get_db)):
    """Mark all notifications as read for a user."""
    result = await db.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
    )
    for n in result.scalars().all():
        n.is_read = True
    await db.commit()
    return {"ok": True}


@router.get("/users/{user_id}/notifications/stream")
async def notification_stream(user_id: str):
    """SSE stream for real-time notifications. No Redis needed — polls DB every 3s."""
    async def event_generator():
        last_count = -1
        while True:
            try:
                async with async_session() as db:
                    result = await db.execute(
                        select(func.count(Notification.id)).where(
                            Notification.user_id == user_id,
                            Notification.is_read == False,  # noqa: E712
                        )
                    )
                    count = result.scalar() or 0
                    if count != last_count:
                        last_count = count
                        # Also fetch latest unread notifications
                        notifs = await db.execute(
                            select(Notification)
                            .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
                            .order_by(Notification.created_at.desc())
                            .limit(5)
                        )
                        latest = [
                            {"id": n.id, "type": n.notification_type, "title": n.title, "body": n.body}
                            for n in notifs.scalars().all()
                        ]
                        yield f"data: {json.dumps({'count': count, 'latest': latest})}\n\n"
            except Exception:
                pass
            await asyncio.sleep(3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
