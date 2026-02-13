"""Morning briefing route — proactive agent intelligence."""

import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import generate_briefing
from src.crypto import decrypt_text
from src.database import get_db
from src.models import (
    AgentTask,
    CapsuleNetworkAccess,
    ConnectionRequest,
    KnowledgeCapsule,
    Network,
    NetworkMembership,
    Notification,
    User,
)
from src.schemas import BriefingResponse

router = APIRouter(prefix="/api", tags=["briefing"])

# Simple in-memory cache: user_id -> (briefing_text, generated_at)
_briefing_cache: dict[str, tuple[str, datetime]] = {}
CACHE_TTL_MINUTES = 30


@router.get("/users/{user_id}/briefing", response_model=BriefingResponse)
async def get_briefing(user_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a morning briefing for the user."""
    from src.main import vault_keys

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    # Check cache
    if user_id in _briefing_cache:
        cached_text, cached_at = _briefing_cache[user_id]
        if (datetime.now(timezone.utc) - cached_at).total_seconds() < CACHE_TTL_MINUTES * 60:
            return BriefingResponse(
                user_id=user_id,
                briefing=cached_text,
                generated_at=cached_at,
            )

    vault_key = vault_keys.get(user_id)
    if not vault_key:
        raise HTTPException(400, "Vault key not available")

    # 1. Load user's schedule/temporary capsules
    result = await db.execute(
        select(KnowledgeCapsule).where(
            KnowledgeCapsule.owner_id == user_id,
            KnowledgeCapsule.is_archived == False,  # noqa: E712
            KnowledgeCapsule.capsule_type.in_(["schedule", "procedure", "memory"]),
        ).limit(15)
    )
    user_capsules = []
    for c in result.scalars().all():
        try:
            content = decrypt_text(c.content_encrypted, vault_key)
        except Exception:
            content = "[Could not decrypt]"
        user_capsules.append({
            "capsule_type": c.capsule_type,
            "title": c.title,
            "content": content,
            "tier": c.tier,
        })

    # 2. Load pending tasks
    tasks_result = await db.execute(
        select(AgentTask).where(
            AgentTask.owner_id == user_id,
            AgentTask.status.in_(["pending", "in_progress"]),
        ).limit(10)
    )
    pending_tasks = [
        {"title": t.title, "description": t.description, "status": t.status}
        for t in tasks_result.scalars().all()
    ]

    # 3. Load recent network capsules (last 48h)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    user_network_ids_result = await db.execute(
        select(NetworkMembership.network_id).where(
            NetworkMembership.user_id == user_id
        )
    )
    user_network_ids = [r for r in user_network_ids_result.scalars().all()]

    recent_network_capsules = []
    if user_network_ids:
        net_capsule_result = await db.execute(
            select(KnowledgeCapsule)
            .join(CapsuleNetworkAccess, CapsuleNetworkAccess.capsule_id == KnowledgeCapsule.id)
            .where(
                CapsuleNetworkAccess.network_id.in_(user_network_ids),
                KnowledgeCapsule.owner_id != user_id,
                KnowledgeCapsule.created_at >= cutoff,
                KnowledgeCapsule.is_archived == False,  # noqa: E712
            ).limit(10)
        )
        for c in net_capsule_result.scalars().all():
            owner = await db.get(User, c.owner_id)
            try:
                content = decrypt_text(c.content_encrypted, vault_key)
            except Exception:
                content = "[encrypted]"
            recent_network_capsules.append({
                "owner_name": owner.display_name if owner else "Unknown",
                "title": c.title,
                "content": content,
                "capsule_type": c.capsule_type,
            })

    # 4. Pending connection requests
    pending_req_result = await db.execute(
        select(ConnectionRequest).where(
            ConnectionRequest.to_user_id == user_id,
            ConnectionRequest.status == "pending",
        )
    )
    pending_requests = len(list(pending_req_result.scalars().all()))

    # 5. Unread notifications
    notif_result = await db.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
    )
    unread_notifications = len(list(notif_result.scalars().all()))

    # 6. Generate briefing with Opus 4.6
    briefing_text = await generate_briefing(
        owner_name=user.display_name,
        capsules=user_capsules,
        pending_tasks=pending_tasks,
        recent_network_capsules=recent_network_capsules,
        pending_requests=pending_requests,
        unread_notifications=unread_notifications,
    )

    now = datetime.now(timezone.utc)
    _briefing_cache[user_id] = (briefing_text, now)

    return BriefingResponse(
        user_id=user_id,
        briefing=briefing_text,
        generated_at=now,
    )
