"""Memory API — NullClaw-compatible memory backend.

Wire format matches NullClaw api.zig exactly so NullClaw works with zero code changes:

  PUT    /api/memory/{ns}/memories/{key}          — store (client-controlled key)
  GET    /api/memory/{ns}/memories                — list
  POST   /api/memory/{ns}/memories/search         — FTS5 search
  DELETE /api/memory/{ns}/memories/{key}          — soft-delete
  GET    /api/memory/{ns}/health                  — health check
  POST   /api/memory/{ns}/sessions/{sid}/messages — save session message

Auth: Authorization: Bearer tm_<token> (channel_tokens table, same as /api/channels/*)
{ns}: username OR user_id — validated against token owner_id.

NullClaw config to connect:
  {
    "memory": {
      "backend": "api",
      "api": {
        "base_url": "http://localhost:9000/api/memory/<username>",
        "api_key": "tm_<channel_token>"
      }
    }
  }
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import transit_bridge
from src.database import get_db
from src.models import ChannelToken, KnowledgeCapsule, User, new_uuid

log = logging.getLogger(__name__)

router = APIRouter(tags=["memory"])

# ── Auth ──────────────────────────────────────────────────────────────────────


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _bearer_auth(request: Request, db: AsyncSession) -> str:
    """Validate Bearer tm_<token>, return owner_id."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer tm_"):
        raise HTTPException(401, "Bearer tm_<token> required")

    raw = auth.removeprefix("Bearer ")
    result = await db.execute(
        select(ChannelToken).where(
            ChannelToken.token_hash == _hash_token(raw),
            ChannelToken.revoked_at.is_(None),
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(401, "Invalid or revoked channel token")

    try:
        token.last_used_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception:
        await db.rollback()

    return token.owner_id


async def _resolve_ns(ns: str, owner_id: str, db: AsyncSession) -> str:
    """Resolve {ns} (username or user_id) to user_id, verify matches token owner."""
    result = await db.execute(select(User).where(User.username == ns))
    user = result.scalar_one_or_none()
    if not user:
        result = await db.execute(select(User).where(User.id == ns))
        user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    if user.id != owner_id:
        raise HTTPException(403, "Token does not belong to this user namespace")
    return user.id


# ── Category mapping ──────────────────────────────────────────────────────────

_NC_TO_TM: dict[str, dict] = {
    "core":             {"freshness": "permanent", "category": ""},
    "daily":            {"freshness": "ephemeral",  "category": ""},
    "conversation":     {"freshness": "ephemeral",  "category": ""},
    "custom:health":    {"freshness": "permanent",  "category": "medical"},
    "custom:financial": {"freshness": "permanent",  "category": "financial"},
    "custom:legal":     {"freshness": "permanent",  "category": "legal"},
}

_NC_META_PREFIX = "nullclaw:"


def _nc_to_capsule(nc_category: str) -> dict:
    return _NC_TO_TM.get(nc_category, {"freshness": "permanent", "category": ""})


def _encode_title(nc_category: str, session_id: str | None) -> str:
    meta = json.dumps({"category": nc_category, "session_id": session_id})
    return f"{_NC_META_PREFIX}{meta}"


def _decode_title(title: str) -> dict:
    if title and title.startswith(_NC_META_PREFIX):
        try:
            return json.loads(title[len(_NC_META_PREFIX):])
        except Exception:
            pass
    return {}


def _capsule_nc_category(cap: KnowledgeCapsule, meta: dict) -> str:
    stored = meta.get("category")
    if stored:
        return stored
    if cap.category == "medical":
        return "custom:health"
    if cap.category == "financial":
        return "custom:financial"
    if cap.category == "legal":
        return "custom:legal"
    return "daily" if cap.freshness == "ephemeral" else "core"


def _to_entry(cap: KnowledgeCapsule, content: str, score: float = 0.0) -> dict:
    meta = _decode_title(cap.title)
    return {
        "id": cap.id,
        "key": cap.id,
        "content": content,
        "category": _capsule_nc_category(cap, meta),
        "timestamp": cap.created_at.isoformat(),
        "session_id": meta.get("session_id"),
        "score": score,
    }


# ── Health ────────────────────────────────────────────────────────────────────


@router.get("/api/memory/{ns}/health")
async def memory_health(ns: str):
    """NullClaw health probe — no auth required."""
    return {"status": "ok", "backend": "trustmesh", "version": "1.0"}


# ── Store ─────────────────────────────────────────────────────────────────────


class MemoryStore(BaseModel):
    content: str
    category: str = "core"
    session_id: str | None = None


@router.put("/api/memory/{ns}/memories/{key}")
async def memory_store(
    ns: str,
    key: str,
    body: MemoryStore,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Upsert a memory. NullClaw sends client-generated UUID as key."""
    owner_id = await _bearer_auth(request, db)
    user_id = await _resolve_ns(ns, owner_id, db)

    if not transit_bridge.has_key(user_id):
        raise HTTPException(503, "Vault key not loaded — user must log in to TrustMesh first")

    tm = _nc_to_capsule(body.category)
    title = _encode_title(body.category, body.session_id)
    encrypted = transit_bridge.encrypt_text(user_id, body.content)

    result = await db.execute(
        select(KnowledgeCapsule).where(
            KnowledgeCapsule.id == key,
            KnowledgeCapsule.owner_id == user_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.content_encrypted = encrypted
        existing.title = title
        existing.freshness = tm["freshness"]
        existing.category = tm["category"]
        existing.updated_at = datetime.now(timezone.utc)
        await db.commit()
        cap = existing
    else:
        cap = KnowledgeCapsule(
            id=key,
            owner_id=user_id,
            capsule_type="memory",
            title=title,
            content_encrypted=encrypted,
            visibility="private",
            freshness=tm["freshness"],
            category=tm["category"],
        )
        db.add(cap)
        await db.commit()

    # Update FTS5 index (best-effort)
    try:
        from src.embeddings import upsert_capsule_embedding
        upsert_capsule_embedding(
            key, body.content,
            {"capsule_id": key, "owner_id": user_id, "visibility": "private"},
            category=tm["category"] or "general",
        )
    except Exception:
        pass

    return _to_entry(cap, body.content)


# ── List ──────────────────────────────────────────────────────────────────────


@router.get("/api/memory/{ns}/memories")
async def memory_list(
    ns: str,
    request: Request,
    category: str | None = None,
    session_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    owner_id = await _bearer_auth(request, db)
    user_id = await _resolve_ns(ns, owner_id, db)

    result = await db.execute(
        select(KnowledgeCapsule).where(
            KnowledgeCapsule.owner_id == user_id,
            KnowledgeCapsule.capsule_type == "memory",
            KnowledgeCapsule.is_archived == False,  # noqa: E712
            KnowledgeCapsule.title.startswith(_NC_META_PREFIX),
        ).order_by(KnowledgeCapsule.created_at.desc())
    )
    caps = result.scalars().all()

    entries = []
    for cap in caps:
        meta = _decode_title(cap.title)
        nc_cat = _capsule_nc_category(cap, meta)

        if category and nc_cat != category:
            continue
        if session_id and meta.get("session_id") != session_id:
            continue

        try:
            content = transit_bridge.decrypt_text(user_id, cap.content_encrypted)
        except Exception:
            continue

        entries.append(_to_entry(cap, content))

    return {"entries": entries}


# ── Search ────────────────────────────────────────────────────────────────────


class MemorySearch(BaseModel):
    query: str
    limit: int = 10
    session_id: str | None = None


@router.post("/api/memory/{ns}/memories/search")
async def memory_search(
    ns: str,
    body: MemorySearch,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    owner_id = await _bearer_auth(request, db)
    user_id = await _resolve_ns(ns, owner_id, db)

    # Gather memory capsule IDs for this user (FTS5 needs an allowlist)
    id_result = await db.execute(
        select(KnowledgeCapsule.id).where(
            KnowledgeCapsule.owner_id == user_id,
            KnowledgeCapsule.capsule_type == "memory",
            KnowledgeCapsule.is_archived == False,  # noqa: E712
            KnowledgeCapsule.title.startswith(_NC_META_PREFIX),
        )
    )
    accessible_ids = list(id_result.scalars().all())

    ranked_ids: list[str] = []
    try:
        from src.embeddings import search_capsules
        ranked_ids = search_capsules(body.query, accessible_ids, top_k=body.limit)
    except Exception:
        pass

    entries = []
    for cap_id in ranked_ids:
        result = await db.execute(
            select(KnowledgeCapsule).where(KnowledgeCapsule.id == cap_id)
        )
        cap = result.scalar_one_or_none()
        if not cap:
            continue

        meta = _decode_title(cap.title)
        if body.session_id and meta.get("session_id") != body.session_id:
            continue

        try:
            content = transit_bridge.decrypt_text(user_id, cap.content_encrypted)
        except Exception:
            continue

        entries.append(_to_entry(cap, content))
        if len(entries) >= body.limit:
            break

    return {"entries": entries}


# ── Delete ────────────────────────────────────────────────────────────────────


@router.delete("/api/memory/{ns}/memories/{key}")
async def memory_forget(
    ns: str,
    key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    owner_id = await _bearer_auth(request, db)
    user_id = await _resolve_ns(ns, owner_id, db)

    result = await db.execute(
        select(KnowledgeCapsule).where(
            KnowledgeCapsule.id == key,
            KnowledgeCapsule.owner_id == user_id,
        )
    )
    cap = result.scalar_one_or_none()
    if not cap:
        raise HTTPException(404, "Memory not found")

    cap.is_archived = True
    await db.commit()

    try:
        from src.embeddings import delete_capsule_embedding
        delete_capsule_embedding(key)
    except Exception:
        pass

    return {"status": "deleted", "key": key}


# ── Session messages ──────────────────────────────────────────────────────────


class SessionMessage(BaseModel):
    role: str
    content: str


@router.post("/api/memory/{ns}/sessions/{sid}/messages")
async def memory_session_message(
    ns: str,
    sid: str,
    body: SessionMessage,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Store a conversation message as an ephemeral memory capsule."""
    owner_id = await _bearer_auth(request, db)
    user_id = await _resolve_ns(ns, owner_id, db)

    if not transit_bridge.has_key(user_id):
        raise HTTPException(503, "Vault key not loaded")

    content = f"[{body.role}] {body.content}"
    encrypted = transit_bridge.encrypt_text(user_id, content)
    cap = KnowledgeCapsule(
        id=new_uuid(),
        owner_id=user_id,
        capsule_type="memory",
        title=_encode_title("conversation", sid),
        content_encrypted=encrypted,
        visibility="private",
        freshness="ephemeral",
        category="",
    )
    db.add(cap)
    await db.commit()

    return {"status": "saved", "id": cap.id}
