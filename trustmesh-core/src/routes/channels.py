"""Channel bridge routes — ZeroClaw/NullClaw and any AI framework integration.

Works in two modes:
  Zig mode (TRUSTMESH_ZIG_HTTP=1):
    channels.zig validates Bearer tm_<token>, runs pre-flight sensitivity,
    then proxies here with X-Channel-Owner-Id and X-Preflight-Sensitivity headers.

  Python mode (default, docker-compose, uvicorn direct):
    This module validates Bearer tm_<token> directly against the channel_tokens
    DB table, runs Python pre-flight sensitivity, then calls the gossip pipeline.

Routes:
  POST   /api/users/{user_id}/channel-tokens        — create token (session auth)
  GET    /api/users/{user_id}/channel-tokens        — list tokens  (session auth)
  DELETE /api/users/{user_id}/channel-tokens/{id}  — revoke token (session auth)
  POST   /api/channels/message                     — send message  (Bearer auth)
  POST   /api/channels/webhook                     — ZeroClaw wire format (Bearer auth)
"""

import hashlib
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db
from src.gossip import query_agent
from src.models import ChannelToken, User

log = logging.getLogger(__name__)

router = APIRouter(tags=["channels"])


# ── Token management (session auth) ──────────────────────────────────────────


class ChannelTokenCreate(BaseModel):
    name: str
    relationship_type: str | None = None
    scopes: list[str] = ["query", "memory"]


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@router.post("/api/users/{user_id}/channel-tokens")
async def create_channel_token(
    user_id: str,
    body: ChannelTokenCreate,
    auth_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a Bearer token for ZeroClaw, NullClaw, or any AI framework.

    Raw token is returned once and never stored.
    """
    if auth_user_id != user_id:
        raise HTTPException(403, "Cannot create tokens for another user")

    raw_token = "tm_" + secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)

    token = ChannelToken(
        owner_id=user_id,
        token_hash=token_hash,
        name=body.name,
        relationship_type=body.relationship_type,
        scopes=",".join(body.scopes),
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    return {
        "id": token.id,
        "name": token.name,
        "relationship_type": token.relationship_type,
        "scopes": body.scopes,
        "created_at": token.created_at.isoformat(),
        "raw_token": raw_token,  # shown once only
    }


@router.get("/api/users/{user_id}/channel-tokens")
async def list_channel_tokens(
    user_id: str,
    auth_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if auth_user_id != user_id:
        raise HTTPException(403, "Cannot list tokens for another user")

    result = await db.execute(
        select(ChannelToken)
        .where(ChannelToken.owner_id == user_id, ChannelToken.revoked_at.is_(None))
        .order_by(ChannelToken.created_at.desc())
    )
    tokens = result.scalars().all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "relationship_type": t.relationship_type,
            "scopes": t.scopes.split(","),
            "created_at": t.created_at.isoformat(),
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        }
        for t in tokens
    ]


@router.delete("/api/users/{user_id}/channel-tokens/{token_id}")
async def revoke_channel_token(
    user_id: str,
    token_id: str,
    auth_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if auth_user_id != user_id:
        raise HTTPException(403, "Cannot revoke tokens for another user")

    result = await db.execute(
        select(ChannelToken).where(
            ChannelToken.id == token_id,
            ChannelToken.owner_id == user_id,
            ChannelToken.revoked_at.is_(None),
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(404, "Token not found")

    token.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "revoked"}


# ── Bearer token auth helper ──────────────────────────────────────────────────

_SENSITIVE_REL_TYPES = {"healthcare", "legal", "financial"}
_SENSITIVE_KEYWORDS = {
    "dialysis", "blood type", "blood pressure", "allergy", "medication",
    "prescription", "surgery", "medical", "dnr", "do not resuscitate",
    "insurance", "diagnosis", "social security", "ssn", "bank account",
    "credit card", "password", "private key", "attorney", "legal",
}


def _preflight_sensitivity(text: str, relationship_type: str | None) -> str:
    """Fast Python pre-flight sensitivity check."""
    if relationship_type and relationship_type.lower() in _SENSITIVE_REL_TYPES:
        return "sensitive"
    text_lower = text.lower()
    if any(kw in text_lower for kw in _SENSITIVE_KEYWORDS):
        return "sensitive"
    return "standard"


async def _get_channel_context(
    request: Request, db: AsyncSession
) -> tuple[str, str]:
    """Return (owner_id, sensitivity_hint).

    Zig mode: reads X-Channel-Owner-Id injected by channels.zig.
    Python mode: validates Bearer tm_<token> against channel_tokens table.
    """
    # Zig-injected header takes precedence (Zig already validated the token)
    owner_id = request.headers.get("x-channel-owner-id")
    if owner_id:
        sensitivity_hint = request.headers.get("x-preflight-sensitivity", "standard")
        return owner_id, sensitivity_hint

    # Python-native Bearer auth
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer tm_"):
        raise HTTPException(401, "Bearer tm_<token> required")

    raw_token = auth_header.removeprefix("Bearer ")
    token_hash = _hash_token(raw_token)

    result = await db.execute(
        select(ChannelToken).where(
            ChannelToken.token_hash == token_hash,
            ChannelToken.revoked_at.is_(None),
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(401, "Invalid or revoked channel token")

    # Update last_used_at (best-effort, don't fail the request)
    try:
        token.last_used_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception:
        await db.rollback()

    # Read body early so _preflight_sensitivity can see the message text
    # (body is cached by FastAPI; re-reading in the route handler is safe)
    try:
        body = await request.json()
        message = body.get("message", "")
    except Exception:
        message = ""

    sensitivity_hint = _preflight_sensitivity(message, token.relationship_type)
    return token.owner_id, sensitivity_hint


# ── Channel endpoints (Bearer auth) ──────────────────────────────────────────


@router.post("/api/channels/message")
async def channel_message(request: Request, db: AsyncSession = Depends(get_db)):
    """General channel message. Accepts `to_username` in metadata for cross-user queries."""
    owner_id, sensitivity_hint = await _get_channel_context(request, db)

    body = await request.json()
    message = body.get("message", "")
    if not message:
        raise HTTPException(400, "message field required")

    to_username = (body.get("metadata") or {}).get("to_username")
    if to_username:
        result_row = await db.execute(select(User).where(User.username == to_username))
        target_user = result_row.scalar_one_or_none()
        if not target_user:
            raise HTTPException(404, "Target user not found")
        result = await query_agent(db, owner_id, target_user.id, message, sensitivity_hint=sensitivity_hint)
    else:
        result = await query_agent(db, owner_id, owner_id, message, sensitivity_hint=sensitivity_hint)

    return {
        "response": result["response"],
        "model": (result.get("routing") or {}).get("provider"),
        "sensitivity": sensitivity_hint,
        "trust_level": result.get("trust_level"),
        "latency_ms": result.get("latency_ms"),
    }


@router.post("/api/channels/webhook")
async def channel_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """ZeroClaw wire format: {"message":"..."} → {"response":"...","model":"..."}."""
    owner_id, sensitivity_hint = await _get_channel_context(request, db)

    body = await request.json()
    message = body.get("message", "")
    if not message:
        raise HTTPException(400, "message field required")

    result = await query_agent(db, owner_id, owner_id, message, sensitivity_hint=sensitivity_hint)
    return {
        "response": result["response"],
        "model": (result.get("routing") or {}).get("provider"),
    }
