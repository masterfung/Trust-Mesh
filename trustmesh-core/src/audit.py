"""Audit logging helpers for TrustMesh.

All security-relevant events (emergency access, queries, auth) are logged
with full context for accountability and patient notification.
"""

import json
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AuditLog, Notification


async def log_event(
    db: AsyncSession,
    *,
    actor_user_id: str | None = None,
    actor_did: str | None = None,
    actor_role: str | None = None,
    actor_institution: str | None = None,
    target_user_id: str | None = None,
    action: str,
    event_type: str,
    capsule_ids_accessed: list[str] | None = None,
    categories_accessed: list[str] | None = None,
    token_hash: str | None = None,
    token_role: str | None = None,
    token_expires_at: datetime | None = None,
    case_id: str | None = None,
    reason: str | None = None,
    query_id: str | None = None,
    decision: str = "allowed",
    details: dict | None = None,
    notify_target: bool = False,
    notification_title: str | None = None,
    notification_body: str | None = None,
) -> AuditLog:
    """Create an audit log entry and optionally notify the target user."""
    entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_did=actor_did,
        actor_role=actor_role,
        actor_institution=actor_institution,
        target_user_id=target_user_id,
        action=action,
        event_type=event_type,
        capsule_ids_accessed=json.dumps(capsule_ids_accessed) if capsule_ids_accessed else None,
        categories_accessed=json.dumps(categories_accessed) if categories_accessed else None,
        token_hash=token_hash,
        token_role=token_role,
        token_expires_at=token_expires_at,
        case_id=case_id,
        reason=reason,
        query_id=query_id,
        decision=decision,
        details=json.dumps(details) if details else None,
    )
    db.add(entry)
    await db.flush()

    # Notify target user if requested
    if notify_target and target_user_id and notification_title:
        notification = Notification(
            user_id=target_user_id,
            notification_type="emergency_access",
            title=notification_title,
            body=notification_body or "",
            related_id=entry.id,
        )
        db.add(notification)

    return entry
