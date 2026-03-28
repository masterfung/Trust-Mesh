"""Knowledge capsule CRUD routes."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import log_event
from src.auth import get_current_user_id
from src.crypto import content_hash
from src import transit_bridge
from src.database import get_db
from src.embeddings import delete_capsule_embedding, move_capsule_embedding, upsert_capsule_embedding
from src.models import CapsuleNetworkAccess, CapsuleVersion, KnowledgeCapsule, Network, NetworkMembership, User
from src.schemas import CapsuleCreate, CapsuleResponse, CapsuleShareRequest, CapsuleUpdate

router = APIRouter(prefix="/api", tags=["capsules"])


async def _notify_pending_requesters(db: AsyncSession, user_id: str) -> None:
    """After a user saves shared data, notify any pods waiting for it.

    Looks up pending DataRequest records for this user and POSTs
    /api/pod/peer_data_ready to each requester's pod so their timeline
    follow-up task can fire.
    """
    import logging
    import httpx
    from datetime import datetime, timezone
    from src.models import DataRequest

    log = logging.getLogger(__name__)
    try:
        result = await db.execute(
            select(DataRequest).where(
                DataRequest.recipient_user_id == user_id,
                DataRequest.status == "pending",
            )
        )
        requests = result.scalars().all()
        if not requests:
            return

        async with httpx.AsyncClient(timeout=8) as client:
            for req in requests:
                try:
                    await client.post(
                        f"{req.requester_pod_url.rstrip('/')}/api/pod/peer_data_ready",
                        json={
                            "from_did": "local",
                            "for_user_id": req.requester_user_id,
                            "target_user_id": user_id,
                            "category": "general",
                        },
                    )
                    req.status = "fulfilled"
                    req.fulfilled_at = datetime.now(timezone.utc)
                    log.info("peer_data_ready sent to %s for user %s", req.requester_pod_url, req.requester_user_id)
                except Exception as e:
                    log.warning("Failed to notify requester pod %s: %s", req.requester_pod_url, e)

        await db.commit()
    except Exception as e:
        log.warning("_notify_pending_requesters failed: %s", e)


def _push_timeline_event(event_type: str):
    """Push a capsule event to the timeline engine (best-effort, no-op if unavailable)."""
    try:
        from src.routes.timeline import _get_optional_engine
        engine = _get_optional_engine()
        if engine and engine.is_running:
            from src.timeline_bridge import EventSource
            engine.push_event(event_type, EventSource.SYSTEM)
    except Exception:
        pass  # Timeline is optional — never block capsule operations


def _check_vault_key(user_id: str) -> None:
    """Verify vault key is loaded for user. Raises 500 if not."""
    if not transit_bridge.has_key(user_id):
        raise HTTPException(500, "Vault key not loaded")


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


def _capsule_to_response(
    capsule: KnowledgeCapsule,
    content: str,
    network_ids: list[str],
    owner_display_name: str | None = None,
    network_names: list[str] | None = None,
) -> CapsuleResponse:
    return CapsuleResponse(
        id=capsule.id,
        owner_id=capsule.owner_id,
        owner_display_name=owner_display_name,
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
        supersedes_id=capsule.supersedes_id,
        authority_weight=capsule.authority_weight,
        created_at=capsule.created_at,
        updated_at=capsule.updated_at,
        network_ids=network_ids,
        network_names=network_names or [],
    )


@router.post("/users/{user_id}/capsules", response_model=CapsuleResponse)
async def create_capsule(
    user_id: str, data: CapsuleCreate, db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Add a knowledge capsule to a user's vault."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    _check_vault_key(user_id)

    network_ids = await _validate_network_ids(db, user_id, data.network_ids)

    # Supersession validation
    supersedes_id = None
    authority_weight = 1.0
    if data.supersedes_id:
        target = await db.get(KnowledgeCapsule, data.supersedes_id)
        if not target:
            raise HTTPException(404, "Superseded capsule not found")
        if target.owner_id != user_id:
            raise HTTPException(400, "Can only supersede your own capsules")
        supersedes_id = data.supersedes_id
    # Authority weight based on user type
    user = await db.get(User, user_id)
    if user:
        authority_weight = {"person": 1.0, "organization": 2.0, "government": 3.0}.get(user.user_type, 1.0)

    capsule = KnowledgeCapsule(
        owner_id=user_id,
        capsule_type=data.capsule_type,
        title=data.title,
        content_encrypted=transit_bridge.encrypt_text(user_id, data.content),
        content_hash=content_hash(data.content),
        visibility=data.effective_visibility(),
        emergency_accessible=data.emergency_accessible,
        can_reshare=data.can_reshare,
        category=data.category,
        embedding_collection=data.category or "general",
        context=data.context,
        freshness=data.freshness,
        expires_at=data.expires_at,
        auto_archive_days=data.auto_archive_days,
        supersedes_id=supersedes_id,
        authority_weight=authority_weight,
    )
    db.add(capsule)
    await db.flush()

    # Add network access
    for nid in network_ids:
        db.add(CapsuleNetworkAccess(capsule_id=capsule.id, network_id=nid))

    await db.commit()
    await db.refresh(capsule)

    # Embed for semantic search (category-scoped)
    upsert_capsule_embedding(
        capsule.id,
        f"{data.title}: {data.content}",
        {"capsule_id": capsule.id, "owner_id": user_id, "tier": data.tier},
        category=data.category or "general",
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

    # Push timeline event (fires any event-triggered entries watching for capsule changes)
    _push_timeline_event(f"capsule.created.{data.category or 'general'}")

    # Notify requesters who asked for data from this user (async, best-effort)
    if capsule.visibility in ("open", "internal"):
        import asyncio as _asyncio
        _asyncio.ensure_future(_notify_pending_requesters(db, user_id))

    # Resolve network names
    network_names = []
    if network_ids:
        net_result = await db.execute(select(Network).where(Network.id.in_(network_ids)))
        net_map = {n.id: n.name for n in net_result.scalars().all()}
        network_names = [net_map.get(nid, nid[:8]) for nid in network_ids]

    return _capsule_to_response(capsule, data.content, network_ids, user.display_name if user else None, network_names)


@router.get("/users/{user_id}/capsules", response_model=list[CapsuleResponse])
async def list_capsules(user_id: str, context: str | None = None,
                        db: AsyncSession = Depends(get_db),
                        auth_user_id: str = Depends(get_current_user_id)):
    """List all capsules for a user (owner view). Optional context filter."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    _check_vault_key(user_id)

    filters = [KnowledgeCapsule.owner_id == user_id]
    filters.append(KnowledgeCapsule.deleted_at == None)  # noqa: E711
    if context and context != "all":
        filters.append(KnowledgeCapsule.context.in_([context, "both"]))

    result = await db.execute(
        select(KnowledgeCapsule)
        .where(*filters)
        .order_by(KnowledgeCapsule.created_at.desc())
    )
    capsules = result.scalars().all()

    # Load owner display name once (all capsules belong to same user)
    owner = await db.get(User, user_id)
    owner_display_name = owner.display_name if owner else None

    # Build network name map for resolving network_ids -> names
    all_network_ids = set()
    capsule_network_map: dict[str, list[str]] = {}
    for c in capsules:
        na_result = await db.execute(
            select(CapsuleNetworkAccess.network_id).where(
                CapsuleNetworkAccess.capsule_id == c.id
            )
        )
        nids = list(na_result.scalars().all())
        capsule_network_map[c.id] = nids
        all_network_ids.update(nids)

    network_name_map: dict[str, str] = {}
    if all_network_ids:
        net_result = await db.execute(
            select(Network).where(Network.id.in_(all_network_ids))
        )
        for net in net_result.scalars().all():
            network_name_map[net.id] = net.name

    responses = []
    for c in capsules:
        try:
            content = transit_bridge.decrypt_text(user_id, c.content_encrypted)
        except Exception:
            content = "Content is securely encrypted. Please log in again to refresh your vault key."
        network_ids = capsule_network_map.get(c.id, [])
        network_names = [network_name_map.get(nid, nid[:8]) for nid in network_ids]
        responses.append(_capsule_to_response(c, content, network_ids, owner_display_name, network_names))
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

    _check_vault_key(capsule.owner_id)

    # Compute effective visibility once (used in version tracking and field update)
    eff_vis = data.effective_visibility()

    # Track changes for version history
    changed_fields = {}
    if data.title is not None and data.title != capsule.title:
        changed_fields["title"] = {"old": capsule.title, "new": data.title}
    if data.content is not None:
        changed_fields["content"] = {"old": "[encrypted]", "new": "[encrypted]"}
    if eff_vis is not None and eff_vis != capsule.visibility:
        changed_fields["visibility"] = {"old": capsule.visibility, "new": eff_vis}
    if data.emergency_accessible is not None and data.emergency_accessible != capsule.emergency_accessible:
        changed_fields["emergency_accessible"] = {"old": capsule.emergency_accessible, "new": data.emergency_accessible}
    if data.can_reshare is not None and data.can_reshare != capsule.can_reshare:
        changed_fields["can_reshare"] = {"old": capsule.can_reshare, "new": data.can_reshare}
    if data.category is not None and data.category != capsule.category:
        changed_fields["category"] = {"old": capsule.category, "new": data.category}

    # Save version if anything changed
    if changed_fields:
        from sqlalchemy import func
        version_count = await db.execute(
            select(func.count()).where(CapsuleVersion.capsule_id == capsule_id)
        )
        next_version = (version_count.scalar() or 0) + 1
        version = CapsuleVersion(
            capsule_id=capsule_id,
            version_number=next_version,
            changed_by=auth_user_id,
            changed_fields=json.dumps(changed_fields),
        )
        db.add(version)

    if data.title is not None:
        capsule.title = data.title
    if data.capsule_type is not None:
        capsule.capsule_type = data.capsule_type
    if data.content is not None:
        capsule.content_encrypted = transit_bridge.encrypt_text(capsule.owner_id, data.content)
        capsule.content_hash = content_hash(data.content)
    if eff_vis is not None:
        capsule.visibility = eff_vis
    if data.emergency_accessible is not None:
        capsule.emergency_accessible = data.emergency_accessible
    if data.can_reshare is not None:
        capsule.can_reshare = data.can_reshare
    old_category = capsule.embedding_collection or capsule.category or "general"
    if data.category is not None:
        capsule.category = data.category
        capsule.embedding_collection = data.category or "general"
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

    # Re-embed (move between collections if category changed)
    try:
        content = transit_bridge.decrypt_text(capsule.owner_id, capsule.content_encrypted)
    except Exception:
        content = ""
    new_category = capsule.embedding_collection or capsule.category or "general"
    embed_meta = {"capsule_id": capsule.id, "owner_id": capsule.owner_id, "tier": capsule.tier, "visibility": capsule.visibility}
    if old_category != new_category:
        move_capsule_embedding(capsule.id, f"{capsule.title}: {content}", embed_meta, old_category, new_category)
    else:
        upsert_capsule_embedding(capsule.id, f"{capsule.title}: {content}", embed_meta, category=new_category)

    # Audit log
    await log_event(
        db, actor_user_id=auth_user_id, target_user_id=capsule.owner_id,
        event_type="capsule", action="capsule_updated",
        details={"capsule_id": capsule_id, "title": capsule.title},
    )
    await db.commit()

    # Push timeline event
    _push_timeline_event(f"capsule.updated.{capsule.category or 'general'}")

    na_result = await db.execute(
        select(CapsuleNetworkAccess.network_id).where(CapsuleNetworkAccess.capsule_id == capsule_id)
    )
    network_ids = list(na_result.scalars().all())

    # Resolve owner name and network names
    owner = await db.get(User, capsule.owner_id)
    network_names = []
    if network_ids:
        net_result = await db.execute(select(Network).where(Network.id.in_(network_ids)))
        net_map = {n.id: n.name for n in net_result.scalars().all()}
        network_names = [net_map.get(nid, nid[:8]) for nid in network_ids]

    return _capsule_to_response(capsule, content, network_ids, owner.display_name if owner else None, network_names)


@router.delete("/capsules/{capsule_id}")
async def delete_capsule(capsule_id: str, db: AsyncSession = Depends(get_db),
                         auth_user_id: str = Depends(get_current_user_id)):
    """Soft-delete a capsule (marks deleted_at, archives it)."""
    capsule = await db.get(KnowledgeCapsule, capsule_id)
    if not capsule:
        raise HTTPException(404, "Capsule not found")
    if capsule.owner_id != auth_user_id:
        raise HTTPException(403, "Access denied")

    title = capsule.title
    embed_cat = capsule.embedding_collection or capsule.category or "general"

    # Soft delete: mark as deleted and archived
    capsule.deleted_at = datetime.now(timezone.utc)
    capsule.is_archived = True
    await db.commit()

    # Remove from search index
    delete_capsule_embedding(capsule_id, category=embed_cat)

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

    try:
        content = transit_bridge.decrypt_text(capsule.owner_id, capsule.content_encrypted)
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

    # Resolve owner name and network names
    owner = await db.get(User, capsule.owner_id)
    network_names = []
    if network_ids:
        net_result = await db.execute(select(Network).where(Network.id.in_(network_ids)))
        net_map = {n.id: n.name for n in net_result.scalars().all()}
        network_names = [net_map.get(nid, nid[:8]) for nid in network_ids]

    return _capsule_to_response(capsule, content, network_ids, owner.display_name if owner else None, network_names)
