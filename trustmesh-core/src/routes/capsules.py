"""Knowledge capsule CRUD routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import log_event
from src.auth import get_current_user_id
from src.crypto import content_hash, decrypt_text, encrypt_text
from src.database import get_db
from src.embeddings import delete_capsule_embedding, upsert_capsule_embedding
from src.models import CapsuleNetworkAccess, KnowledgeCapsule, NetworkMembership
from src.schemas import CapsuleCreate, CapsuleResponse, CapsuleShareRequest, CapsuleUpdate

router = APIRouter(prefix="/api", tags=["capsules"])


def _vault_key_for_user(user_id: str) -> bytes:
    """Get vault key for user. Uses the in-memory key store from main app."""
    from src.main import vault_keys
    key = vault_keys.get(user_id)
    if not key:
        raise HTTPException(500, "Vault key not loaded")
    return key


async def _validate_network_ids(
    db: AsyncSession, user_id: str, network_ids: list[str] | None
) -> list[str]:
    """Validate that the user is a member of each requested network id.

    This prevents injecting CapsuleNetworkAccess rows into networks the caller
    does not belong to.
    """
    if not network_ids:
        return []

    # Preserve caller order but drop duplicates.
    unique_ids = list(dict.fromkeys(network_ids))

    result = await db.execute(
        select(NetworkMembership.network_id).where(
            NetworkMembership.user_id == user_id,
            NetworkMembership.network_id.in_(unique_ids),
        )
    )
    allowed = set(result.scalars().all())
    missing = [nid for nid in unique_ids if nid not in allowed]
    if missing:
        raise HTTPException(400, "Invalid network_ids (must be a member of each network)")

    return unique_ids


def _capsule_to_response(capsule: KnowledgeCapsule, content: str, network_ids: list[str]) -> CapsuleResponse:
    return CapsuleResponse(
        id=capsule.id,
        owner_id=capsule.owner_id,
        capsule_type=capsule.capsule_type,
        title=capsule.title,
        content=content,
        tier=capsule.tier,
        visibility=capsule.visibility,
        emergency_accessible=capsule.emergency_accessible,
        can_reshare=capsule.can_reshare,
        category=capsule.category,
        context=capsule.context,
        freshness=capsule.freshness,
        expires_at=capsule.expires_at,
        last_verified_at=capsule.last_verified_at,
        auto_archive_days=capsule.auto_archive_days,
        is_archived=capsule.is_archived,
        created_at=capsule.created_at,
        updated_at=capsule.updated_at,
        network_ids=network_ids,
    )


@router.post("/users/{user_id}/capsules", response_model=CapsuleResponse)
async def create_capsule(
    user_id: str, data: CapsuleCreate, db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Add a knowledge capsule to a user's vault."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    vault_key = _vault_key_for_user(user_id)

    network_ids = await _validate_network_ids(db, user_id, data.network_ids)

    capsule = KnowledgeCapsule(
        owner_id=user_id,
        capsule_type=data.capsule_type,
        title=data.title,
        content_encrypted=encrypt_text(data.content, vault_key),
        content_hash=content_hash(data.content),
        visibility=data.effective_visibility(),
        emergency_accessible=data.emergency_accessible,
        can_reshare=data.can_reshare,
        category=data.category,
        context=data.context,
        freshness=data.freshness,
        expires_at=data.expires_at,
        auto_archive_days=data.auto_archive_days,
    )
    db.add(capsule)
    await db.flush()

    # Add network access
    for nid in network_ids:
        db.add(CapsuleNetworkAccess(capsule_id=capsule.id, network_id=nid))

    await db.commit()
    await db.refresh(capsule)

    # Embed for semantic search
    upsert_capsule_embedding(
        capsule.id,
        f"{data.title}: {data.content}",
        {"capsule_id": capsule.id, "owner_id": user_id, "tier": data.tier},
    )

    # Audit log
    await log_event(
        db, actor_user_id=user_id, target_user_id=user_id,
        event_type="capsule", action="capsule_created",
        details={"capsule_id": capsule.id, "title": data.title,
                 "capsule_type": data.capsule_type, "visibility": capsule.visibility,
                 "category": data.category},
    )
    await db.commit()

    return _capsule_to_response(capsule, data.content, network_ids)


@router.get("/users/{user_id}/capsules", response_model=list[CapsuleResponse])
async def list_capsules(user_id: str, context: str | None = None,
                        db: AsyncSession = Depends(get_db),
                        auth_user_id: str = Depends(get_current_user_id)):
    """List all capsules for a user (owner view). Optional context filter."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    vault_key = _vault_key_for_user(user_id)

    filters = [KnowledgeCapsule.owner_id == user_id]
    if context and context != "all":
        filters.append(KnowledgeCapsule.context.in_([context, "both"]))

    result = await db.execute(
        select(KnowledgeCapsule)
        .where(*filters)
        .order_by(KnowledgeCapsule.created_at.desc())
    )
    capsules = result.scalars().all()
    responses = []
    for c in capsules:
        try:
            content = decrypt_text(c.content_encrypted, vault_key)
        except Exception:
            content = "Content is securely encrypted. Please log in again to refresh your vault key."
        # Get network IDs
        na_result = await db.execute(
            select(CapsuleNetworkAccess.network_id).where(
                CapsuleNetworkAccess.capsule_id == c.id
            )
        )
        network_ids = list(na_result.scalars().all())
        responses.append(_capsule_to_response(c, content, network_ids))
    return responses


@router.put("/capsules/{capsule_id}", response_model=CapsuleResponse)
async def update_capsule(
    capsule_id: str, data: CapsuleUpdate, db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Update a capsule."""
    capsule = await db.get(KnowledgeCapsule, capsule_id)
    if not capsule:
        raise HTTPException(404, "Capsule not found")
    if capsule.owner_id != auth_user_id:
        raise HTTPException(403, "Access denied")

    vault_key = _vault_key_for_user(capsule.owner_id)

    if data.title is not None:
        capsule.title = data.title
    if data.capsule_type is not None:
        capsule.capsule_type = data.capsule_type
    if data.content is not None:
        capsule.content_encrypted = encrypt_text(data.content, vault_key)
        capsule.content_hash = content_hash(data.content)
    eff_vis = data.effective_visibility()
    if eff_vis is not None:
        capsule.visibility = eff_vis
    if data.emergency_accessible is not None:
        capsule.emergency_accessible = data.emergency_accessible
    if data.can_reshare is not None:
        capsule.can_reshare = data.can_reshare
    if data.category is not None:
        capsule.category = data.category
    if data.freshness is not None:
        capsule.freshness = data.freshness
    if data.expires_at is not None:
        capsule.expires_at = data.expires_at
    if data.auto_archive_days is not None:
        capsule.auto_archive_days = data.auto_archive_days

    if data.network_ids is not None:
        network_ids = await _validate_network_ids(db, capsule.owner_id, data.network_ids)
        # Clear existing and re-add
        existing = await db.execute(
            select(CapsuleNetworkAccess).where(CapsuleNetworkAccess.capsule_id == capsule_id)
        )
        for na in existing.scalars().all():
            await db.delete(na)
        for nid in network_ids:
            db.add(CapsuleNetworkAccess(capsule_id=capsule_id, network_id=nid))

    await db.commit()
    await db.refresh(capsule)

    # Re-embed
    try:
        content = decrypt_text(capsule.content_encrypted, vault_key)
    except Exception:
        content = ""
    upsert_capsule_embedding(
        capsule.id,
        f"{capsule.title}: {content}",
        {"capsule_id": capsule.id, "owner_id": capsule.owner_id, "tier": capsule.tier, "visibility": capsule.visibility},
    )

    # Audit log
    await log_event(
        db, actor_user_id=auth_user_id, target_user_id=capsule.owner_id,
        event_type="capsule", action="capsule_updated",
        details={"capsule_id": capsule_id, "title": capsule.title},
    )
    await db.commit()

    na_result = await db.execute(
        select(CapsuleNetworkAccess.network_id).where(CapsuleNetworkAccess.capsule_id == capsule_id)
    )
    network_ids = list(na_result.scalars().all())
    return _capsule_to_response(capsule, content, network_ids)


@router.delete("/capsules/{capsule_id}")
async def delete_capsule(capsule_id: str, db: AsyncSession = Depends(get_db),
                         auth_user_id: str = Depends(get_current_user_id)):
    """Delete a capsule."""
    capsule = await db.get(KnowledgeCapsule, capsule_id)
    if not capsule:
        raise HTTPException(404, "Capsule not found")
    if capsule.owner_id != auth_user_id:
        raise HTTPException(403, "Access denied")

    # Delete network access
    na_result = await db.execute(
        select(CapsuleNetworkAccess).where(CapsuleNetworkAccess.capsule_id == capsule_id)
    )
    for na in na_result.scalars().all():
        await db.delete(na)

    title = capsule.title
    await db.delete(capsule)
    await db.commit()
    delete_capsule_embedding(capsule_id)

    # Audit log
    await log_event(
        db, actor_user_id=auth_user_id, target_user_id=auth_user_id,
        event_type="capsule", action="capsule_deleted",
        details={"capsule_id": capsule_id, "title": title},
    )
    await db.commit()

    return {"ok": True}


@router.post("/capsules/{capsule_id}/share", response_model=CapsuleResponse)
async def share_capsule(
    capsule_id: str, data: CapsuleShareRequest, db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Share a capsule to network(s)."""
    capsule = await db.get(KnowledgeCapsule, capsule_id)
    if not capsule:
        raise HTTPException(404, "Capsule not found")
    if capsule.owner_id != auth_user_id:
        raise HTTPException(403, "Access denied")

    network_ids = await _validate_network_ids(db, capsule.owner_id, data.network_ids)
    for nid in network_ids:
        existing = await db.execute(
            select(CapsuleNetworkAccess).where(
                CapsuleNetworkAccess.capsule_id == capsule_id,
                CapsuleNetworkAccess.network_id == nid,
            )
        )
        if not existing.scalar_one_or_none():
            db.add(CapsuleNetworkAccess(capsule_id=capsule_id, network_id=nid))

    if capsule.visibility == "private":
        capsule.visibility = "internal"

    await db.commit()
    await db.refresh(capsule)

    vault_key = _vault_key_for_user(capsule.owner_id)
    try:
        content = decrypt_text(capsule.content_encrypted, vault_key)
    except Exception:
        content = "Content is securely encrypted. Please log in again to refresh your vault key."

    na_result = await db.execute(
        select(CapsuleNetworkAccess.network_id).where(CapsuleNetworkAccess.capsule_id == capsule_id)
    )
    network_ids = list(na_result.scalars().all())

    # Audit log
    await log_event(
        db, actor_user_id=auth_user_id, target_user_id=capsule.owner_id,
        event_type="capsule", action="capsule_shared",
        details={"capsule_id": capsule_id, "network_ids": network_ids,
                 "visibility": capsule.visibility},
    )
    await db.commit()

    return _capsule_to_response(capsule, content, network_ids)
