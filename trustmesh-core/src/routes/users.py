"""User signup, profile, discovery, and auth routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import (
    COOKIE_NAME,
    check_rate_limit,
    create_session,
    get_current_user_id,
    get_session_token,
    invalidate_session,
    invalidate_user_sessions,
)
from src.crypto import decrypt, derive_vault_key, encrypt, generate_key
from src.database import get_db
from src.models import Agent, User
from src.schemas import (
    AgentCard,
    AgentResponse,
    LoginRequest,
    UserCreate,
    UserPublic,
    UserResponse,
)

router = APIRouter(prefix="/api", tags=["users"])


def _set_session_cookie(response: JSONResponse, token: str) -> None:
    """Set httpOnly session cookie. XSS-safe: JavaScript cannot read this."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,  # Not accessible to JavaScript — prevents XSS token theft
        samesite="lax",  # CSRF protection — cookie not sent on cross-site POST
        secure=False,  # Set True in production with HTTPS
        max_age=86400,  # 24 hours, matches server-side TTL
        path="/",
    )


def _clear_session_cookie(response: JSONResponse) -> None:
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")


@router.post("/users")
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Create a new user with vault and personal agent. Sets httpOnly session cookie."""
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Username already taken")

    vault_master_key = generate_key()
    derived_key, salt = derive_vault_key(data.password)
    encrypted_vault_key = encrypt(vault_master_key, derived_key)

    user = User(
        username=data.username,
        display_name=data.display_name,
        bio=data.bio,
        is_discoverable=data.is_discoverable,
        vault_key_salt=salt,
        encrypted_vault_key=encrypted_vault_key,
    )
    db.add(user)
    await db.flush()

    agent = Agent(
        owner_id=user.id,
        name=f"{data.display_name}'s Agent",
        personality="Helpful, knowledgeable, and protective of private information",
    )
    db.add(agent)
    await db.commit()
    await db.refresh(user)

    # Store vault key in memory so capsule encryption works immediately
    from src.main import vault_keys
    vault_keys[user.id] = vault_master_key

    token = create_session(user.id)
    user_data = UserResponse.model_validate(user).model_dump(mode="json")
    response = JSONResponse(content=user_data)
    _set_session_cookie(response, token)
    return response


@router.post("/auth/login")
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Authenticate user. Sets httpOnly session cookie (XSS-safe)."""
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "Invalid username or password")

    if not user.vault_key_salt or not user.encrypted_vault_key:
        raise HTTPException(401, "Account not set up properly")

    try:
        derived_key, _ = derive_vault_key(data.password, user.vault_key_salt)
        vault_master_key = decrypt(user.encrypted_vault_key, derived_key)
    except Exception:
        raise HTTPException(401, "Invalid username or password")

    # Load vault key into memory so capsule operations work
    from src.main import vault_keys
    vault_keys[user.id] = vault_master_key

    token = create_session(user.id)
    user_data = UserResponse.model_validate(user).model_dump(mode="json")
    response = JSONResponse(content=user_data)
    _set_session_cookie(response, token)
    return response


@router.post("/auth/logout")
async def logout(request: Request, user_id: str = Depends(get_current_user_id)):
    """Invalidate session and clear httpOnly cookie."""
    token = get_session_token(request)
    if token:
        invalidate_session(token)
    invalidate_user_sessions(user_id)
    response = JSONResponse(content={"status": "ok"})
    _clear_session_cookie(response)
    return response


@router.get("/auth/me", response_model=UserResponse)
async def get_me(
    request: Request,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get current authenticated user from session cookie."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user


@router.get("/users", response_model=list[UserPublic])
async def list_users(db: AsyncSession = Depends(get_db)):
    """List discoverable users."""
    result = await db.execute(
        select(User).where(User.is_discoverable == True).order_by(User.display_name)  # noqa: E712
    )
    return result.scalars().all()


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, db: AsyncSession = Depends(get_db)):
    """Get user profile."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user


@router.get("/users/{user_id}/agent", response_model=AgentResponse)
async def get_agent(user_id: str, db: AsyncSession = Depends(get_db)):
    """Get user's agent details."""
    result = await db.execute(select(Agent).where(Agent.owner_id == user_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@router.get("/users/{user_id}/agent/card", response_model=AgentCard)
async def get_agent_card(user_id: str, db: AsyncSession = Depends(get_db)):
    """Get A2A-compatible agent card."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    result = await db.execute(select(Agent).where(Agent.owner_id == user_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    return AgentCard(
        name=agent.name,
        description=agent.personality,
        owner=UserPublic.model_validate(user),
    )
