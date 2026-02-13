"""Audit log routes — view security and access logs."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models import AuditLog, User
from src.schemas import AuditLogResponse

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/users/{user_id}/audit", response_model=list[AuditLogResponse])
async def list_audit_logs(
    user_id: str,
    event_type: str | None = Query(default=None, description="Filter by event_type"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List audit logs for a user (as target or actor)."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    query = select(AuditLog).where(
        (AuditLog.target_user_id == user_id) | (AuditLog.actor_user_id == user_id)
    ).order_by(AuditLog.created_at.desc()).limit(limit)

    if event_type:
        query = query.where(AuditLog.event_type == event_type)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/users/{user_id}/audit/emergency", response_model=list[AuditLogResponse])
async def list_emergency_logs(
    user_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List emergency access audit logs for a user."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    result = await db.execute(
        select(AuditLog).where(
            AuditLog.target_user_id == user_id,
            AuditLog.event_type == "emergency",
        ).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    return result.scalars().all()
