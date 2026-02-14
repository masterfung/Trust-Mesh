"""Vault PIN routes — sovereignty control for governance changes."""

import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.crypto import hash_pin, verify_pin
from src.database import get_db
from src.models import User
from src.schemas import PinSetRequest, PinStatusResponse, PinVerifyRequest, PinVerifyResponse

router = APIRouter(prefix="/api", tags=["pin"])


def _get_pin_tokens() -> dict:
    from src.main import pin_tokens
    return pin_tokens


@router.post("/users/{user_id}/pin", response_model=PinStatusResponse)
async def set_pin(
    user_id: str,
    data: PinSetRequest,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Set or update the user's vault PIN."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    user.pin_hash = hash_pin(data.pin)
    await db.commit()
    return PinStatusResponse(has_pin=True)


@router.post("/users/{user_id}/pin/verify", response_model=PinVerifyResponse)
async def verify_user_pin(
    user_id: str,
    data: PinVerifyRequest,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Verify PIN and return a 5-minute auth token for governance changes."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    if not user.pin_hash:
        raise HTTPException(400, "PIN not set — set a PIN first")

    if not verify_pin(data.pin, user.pin_hash):
        raise HTTPException(403, "Incorrect PIN")

    # Generate a short-lived token
    token = secrets.token_urlsafe(32)
    pin_tokens = _get_pin_tokens()
    pin_tokens[token] = {
        "user_id": user_id,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        "created_at": datetime.now(timezone.utc),
    }

    return PinVerifyResponse(verified=True, token=token, expires_in=300)


@router.get("/users/{user_id}/pin/status", response_model=PinStatusResponse)
async def pin_status(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Check whether user has a PIN set."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    return PinStatusResponse(has_pin=bool(user.pin_hash))
