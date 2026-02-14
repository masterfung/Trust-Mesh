"""User signup, profile, discovery, and auth routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import extract_profile
from src.auth import (
    COOKIE_NAME,
    check_rate_limit,
    create_session,
    get_current_user_id,
    get_session_token,
    invalidate_session,
    invalidate_user_sessions,
)
from src.crypto import decrypt, derive_vault_key, encrypt, generate_key, generate_ed25519_keypair, public_key_to_did, public_key_to_b64
from src.database import get_db
from src.models import Agent, User, parse_profile_data
from src.schemas import (
    AgentCard,
    AgentResponse,
    AgentSkillSchema,
    ContextSwitch,
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

    # Extract structured profile from bio
    profile = await extract_profile(data.bio, data.display_name)

    user = User(
        username=data.username,
        display_name=data.display_name,
        bio=data.bio,
        user_type=data.user_type,
        profile_data=json.dumps(profile) if profile else None,
        is_discoverable=data.is_discoverable,
        vault_key_salt=salt,
        encrypted_vault_key=encrypted_vault_key,
        agent_personality=data.agent_personality,
    )
    db.add(user)
    await db.flush()

    # Generate ed25519 keypair for agent identity
    private_key_bytes, public_key_bytes = generate_ed25519_keypair()
    agent_did = public_key_to_did(public_key_bytes)
    encrypted_privkey = encrypt(private_key_bytes, vault_master_key)

    agent = Agent(
        owner_id=user.id,
        name=f"{data.display_name}'s Agent",
        personality=data.agent_personality or "Helpful, knowledgeable, and protective of private information",
        public_key=public_key_bytes,
        encrypted_private_key=encrypted_privkey,
        did=agent_did,
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

    if user.is_remote:
        raise HTTPException(403, "Remote ghost users cannot log in")

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
    """Invalidate session, clear vault key from memory, and clear httpOnly cookie."""
    from src.main import vault_keys

    token = get_session_token(request)
    if token:
        invalidate_session(token)
    invalidate_user_sessions(user_id)
    vault_keys.pop(user_id, None)  # Clear decrypted vault key from memory
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
    return _user_response(user)


@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_db)):
    """List discoverable users."""
    result = await db.execute(
        select(User).where(User.is_discoverable == True).order_by(User.display_name)  # noqa: E712
    )
    users = result.scalars().all()
    return [_user_response(u) for u in users]


def _user_response(user: User) -> dict:
    """Build a user response dict with parsed profile_data."""
    return UserResponse.model_validate(user).model_dump(mode="json")


@router.get("/users/{user_id}")
async def get_user(user_id: str, db: AsyncSession = Depends(get_db)):
    """Get user profile."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return _user_response(user)


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

    skills = []
    pd = parse_profile_data(user.profile_data)
    if pd:
        for skill in pd.get("skills", []):
            skills.append(AgentSkillSchema(
                id=skill["name"].lower().replace(" ", "_"),
                name=skill["name"],
                description=f"{skill['name']} ({skill.get('category', 'general')})",
                tags=[skill.get("category", "general")],
            ))

    return AgentCard(
        name=agent.name,
        description=agent.personality,
        url=f"/api/users/{user_id}/agent/a2a",
        owner=UserPublic.model_validate(user),
        public_key_b64=public_key_to_b64(agent.public_key) if agent.public_key else None,
        did=agent.did,
        capabilities=["knowledge-query", "trust-aware-sharing"]
        + (["quote-request", "availability-check"] if user.user_type in ("service", "organization") else []),
        skills=skills,
    )


@router.put("/users/{user_id}/context")
async def switch_context(user_id: str, data: ContextSwitch, db: AsyncSession = Depends(get_db),
                         auth_user_id: str = Depends(get_current_user_id)):
    """Switch user's active context mode (work/personal/all)."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.active_context = data.context
    await db.commit()
    return {"context": data.context}
