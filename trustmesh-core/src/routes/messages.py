"""Inter-agent message routes — inbox, sent, mark-read, soft-delete."""

import base64
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["messages"])

MAX_SUBJECT_CHARS = 200
MAX_BODY_CHARS = 10_000


# ─── Helpers ────────────────────────────────────────────────────────────────

def _decrypt_body(message_id: str, recipient_id: str) -> str | None:
    """Decrypt a message body using the transit engine. Returns plaintext or None."""
    from src import transit_bridge
    from src import message_bridge

    b64 = message_bridge.get_body_b64(message_id, recipient_id)
    if not b64:
        return None
    try:
        enc_bytes = base64.b64decode(b64)
        aad = f"message:{message_id}"
        plaintext = transit_bridge.decrypt(recipient_id, enc_bytes, aad=aad)
        return plaintext.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("Failed to decrypt message %s: %s", message_id, e)
        return None


def _enrich_with_body(msg: dict, recipient_id: str) -> dict:
    """Add decrypted body to a message dict if vault key is available."""
    from src import transit_bridge
    if transit_bridge.has_key(recipient_id) and not msg.get("rekey_needed"):
        body = _decrypt_body(msg["id"], recipient_id)
        msg["body"] = body or "[Could not decrypt]"
    else:
        msg["body"] = None  # Body unavailable (offline / rekey pending)
    return msg


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/users/{user_id}/messages/inbox")
async def get_inbox(
    user_id: str,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    auth_user_id: str = Depends(get_current_user_id),
):
    """Return inbox messages for the authenticated user."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    from src import message_bridge
    msgs = message_bridge.list_inbox(user_id, limit=limit, offset=offset, unread_only=unread_only)
    result = [_enrich_with_body(m, user_id) for m in msgs]
    return result


@router.get("/users/{user_id}/messages/sent")
async def get_sent(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    auth_user_id: str = Depends(get_current_user_id),
):
    """Return sent messages for the authenticated user."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    from src import message_bridge
    msgs = message_bridge.list_sent(user_id, limit=limit, offset=offset)
    # For sent messages: decrypt using sender's own key
    result = []
    for m in msgs:
        from src import transit_bridge
        if transit_bridge.has_key(user_id) and not m.get("rekey_needed"):
            body = _decrypt_body(m["id"], m["sender_id"])
            m["body"] = body or "[Could not decrypt]"
        else:
            m["body"] = None
        result.append(m)
    return result


@router.get("/users/{user_id}/messages/unread-count")
async def get_unread_count(
    user_id: str,
    auth_user_id: str = Depends(get_current_user_id),
):
    """Return unread message count for the authenticated user."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    from src import message_bridge
    count = message_bridge.unread_count(user_id)
    return {"count": count}


@router.put("/messages/{message_id}/read")
async def mark_message_read(
    message_id: str,
    auth_user_id: str = Depends(get_current_user_id),
):
    """Mark a message as read (recipient only)."""
    from src import message_bridge
    ok = message_bridge.mark_read(message_id, auth_user_id)
    if not ok:
        raise HTTPException(404, "Message not found or already read")
    return {"status": "ok"}


@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: str,
    auth_user_id: str = Depends(get_current_user_id),
):
    """Soft-delete a message from the recipient's inbox."""
    from src import message_bridge
    ok = message_bridge.soft_delete(message_id, auth_user_id)
    if not ok:
        raise HTTPException(404, "Message not found or access denied")
    return {"status": "ok"}
