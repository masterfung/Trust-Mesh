"""User signup, profile, discovery, and auth routes."""

import json
import os
import logging

log = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import extract_profile
from src import transit_bridge
from src.auth import (
    COOKIE_NAME,
    _compute_fingerprint,
    check_rate_limit,
    create_session,
    get_current_user_id,
    get_session_token,
    invalidate_session,
    invalidate_user_sessions,
    record_failed_login,
)
import base64
from src.crypto import decrypt, derive_vault_key, encrypt, generate_key, generate_ed25519_keypair, generate_x25519_keypair, public_key_to_did, public_key_to_b64
from src.database import get_db
from src.models import Agent, Network, NetworkMembership, User, parse_profile_data
from src.schemas import (
    AgentCard,
    AgentModeUpdate,
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
        secure=not os.getenv("TRUSTMESH_DEV_MODE"),  # Secure in prod, insecure in dev mode
        max_age=86400,  # 24 hours, matches server-side TTL
        path="/",
    )


def _clear_session_cookie(response: JSONResponse) -> None:
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")


@router.post("/users")
async def create_user(data: UserCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Create a new user with vault and personal agent. Sets httpOnly session cookie.

    Username is optional at signup. If not provided, it stays NULL (private user).
    Public handle is claimed later via Go Live / claim-handle endpoint.
    """
    # If username provided (backward compat / demo pods), check uniqueness
    username = data.username
    if username:
        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            raise HTTPException(400, "Username already taken")

    # If email provided, check uniqueness
    email = data.email
    if email:
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            raise HTTPException(400, "Email already in use")

    vault_master_key = generate_key()
    derived_key, salt = derive_vault_key(data.password)
    encrypted_vault_key = encrypt(vault_master_key, derived_key)

    # Extract structured profile from bio
    profile = await extract_profile(data.bio, data.display_name)

    # Normalize legacy "government" user_type
    user_type = data.user_type
    org_subtype = data.org_subtype
    if user_type == "government":
        user_type = "organization"
        if not org_subtype:
            org_subtype = "government"

    # Agent mode: orgs start internal, persons stay private
    agent_mode = "internal" if user_type == "organization" else "private"

    # Orgs are discoverable by default
    is_discoverable = data.is_discoverable
    if user_type == "organization":
        is_discoverable = True

    # Connectivity mode: orgs default to relay_primary (always reachable), persons to invite_only
    connectivity_mode = "relay_primary" if user_type == "organization" else "invite_only"

    user = User(
        username=username,  # NULL for private users, set on Go Live
        email=email,
        display_name=data.display_name,
        bio=data.bio,
        user_type=user_type,
        org_subtype=org_subtype,
        agent_mode=agent_mode,
        profile_data=json.dumps(profile) if profile else None,
        is_discoverable=is_discoverable,
        connectivity_mode=connectivity_mode,
        vault_key_salt=salt,
        encrypted_vault_key=encrypted_vault_key,
        agent_personality=data.agent_personality,
        avatar_url=data.avatar_url or None,
    )
    db.add(user)
    await db.flush()

    # Org pods get two default team pools
    if user_type == "organization":
        all_staff_net = Network(
            owner_id=user.id,
            name="All Staff",
            network_type="team",
            pool_type="org_all_staff",
            join_policy="invite_only",
            context="work",
            is_public=False,
        )
        db.add(all_staff_net)
        await db.flush()
        db.add(NetworkMembership(network_id=all_staff_net.id, user_id=user.id, role="owner"))

        leadership_net = Network(
            owner_id=user.id,
            name="Leadership",
            network_type="team",
            pool_type="org_executives",
            join_policy="invite_only",
            context="work",
            is_public=False,
        )
        db.add(leadership_net)
        await db.flush()
        db.add(NetworkMembership(network_id=leadership_net.id, user_id=user.id, role="owner"))

    # Generate ed25519 keypair for agent identity (signing + DID)
    private_key_bytes, public_key_bytes = generate_ed25519_keypair()
    agent_did = public_key_to_did(public_key_bytes)
    encrypted_privkey = encrypt(private_key_bytes, vault_master_key)

    # Generate X25519 keypair for future relay payload encryption (Phase 2)
    x25519_priv_b64, x25519_pub_b64 = generate_x25519_keypair()
    x25519_priv_bytes = base64.urlsafe_b64decode(x25519_priv_b64 + "==")
    encrypted_x25519_privkey = encrypt(x25519_priv_bytes, vault_master_key)
    del x25519_priv_bytes  # zero ASAP

    agent = Agent(
        owner_id=user.id,
        name=f"{data.display_name}'s Agent",
        personality=data.agent_personality or "Helpful, knowledgeable, and protective of private information",
        public_key=public_key_bytes,
        encrypted_private_key=encrypted_privkey,
        did=agent_did,
        encryption_public_key=x25519_pub_b64,
    )
    _ = encrypted_x25519_privkey  # stored for Phase 2 (relay encryption)
    db.add(agent)
    await db.commit()
    await db.refresh(user)

    # Store vault key in transit engine (key stays in Zig, zeroed in Python)
    transit_bridge.store_key(user.id, vault_master_key)
    transit_bridge._zero_bytes(vault_master_key)

    token = create_session(user.id, fingerprint=_compute_fingerprint(request))
    user_data = UserResponse.model_validate(user).model_dump(mode="json")
    response = JSONResponse(content=user_data)
    _set_session_cookie(response, token)
    return response


@router.post("/auth/login")
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Authenticate user. Sets httpOnly session cookie (XSS-safe).

    Accepts login by display_name (field: name) or username (field: username).
    Private users who haven't claimed a handle login by name.
    """
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    login_id: str = data.email or data.name or data.username or ""
    if not login_id:
        raise HTTPException(401, "Name, email, or username required")

    # Try username first (exact match), then email (exact, case-insensitive), then display_name (case-insensitive)
    looks_like_email = "@" in login_id
    user = None
    result = await db.execute(select(User).where(User.username == login_id))
    user = result.scalar_one_or_none()
    if not user:
        result = await db.execute(
            select(User).where(
                User.email.isnot(None),
                func.lower(User.email) == login_id.strip().lower()
            )
        )
        user = result.scalars().first()
    if not user and not looks_like_email:
        result = await db.execute(
            select(User).where(func.lower(User.display_name) == login_id.lower())
        )
        user = result.scalars().first()
    if not user:
        record_failed_login(client_ip, login_id)
        raise HTTPException(401, "Invalid credentials")

    if user.is_remote:
        raise HTTPException(403, "Remote ghost users cannot log in")

    if not user.vault_key_salt or not user.encrypted_vault_key:
        raise HTTPException(401, "Account not set up properly")

    try:
        derived_key, _ = derive_vault_key(data.password, user.vault_key_salt)
        vault_master_key = decrypt(user.encrypted_vault_key, derived_key)
    except Exception:
        record_failed_login(client_ip, login_id)
        raise HTTPException(401, "Invalid name or password")

    # Store vault key in transit engine (key stays in Zig, zeroed in Python).
    # Skip if already loaded — repeated logins would otherwise exhaust MAX_VERSIONS=8.
    if not transit_bridge.has_key(user.id):
        transit_bridge.store_key(user.id, vault_master_key)
    transit_bridge._zero_bytes(vault_master_key)

    # Re-encrypt any messages that were stored with pod KEK while user was offline
    try:
        from src import message_bridge as _mb
        _mb.rekey_pending(user.id)
    except Exception as _e:
        import logging
        logging.getLogger(__name__).warning("rekey_pending failed for %s: %s", user.id, _e)

    # Session rotation: invalidate all existing sessions before creating new one
    invalidate_user_sessions(user.id)

    token = create_session(user.id, fingerprint=_compute_fingerprint(request))
    user_data = UserResponse.model_validate(user).model_dump(mode="json")

    # Audit: login event
    try:
        from src.audit import log_event
        await log_event(
            db,
            actor_user_id=user.id,
            target_user_id=user.id,
            action="login",
            event_type="auth",
            decision="allowed",
            details={"ip": client_ip},
        )
        await db.commit()
    except Exception as _e:
        log.warning("Audit login failed: %s", _e)

    response = JSONResponse(content=user_data)
    _set_session_cookie(response, token)
    return response


@router.post("/auth/logout")
async def logout(request: Request, user_id: str = Depends(get_current_user_id),
                 db: AsyncSession = Depends(get_db)):
    """Invalidate session, clear vault key from memory, and clear httpOnly cookie."""
    token = get_session_token(request)
    if token:
        invalidate_session(token)
    invalidate_user_sessions(user_id)
    transit_bridge.remove_user(user_id)  # secureZero all key material

    try:
        from src.audit import log_event
        await log_event(
            db,
            actor_user_id=user_id,
            target_user_id=user_id,
            action="logout",
            event_type="auth",
            decision="allowed",
        )
        await db.commit()
    except Exception as _e:
        log.warning("Audit logout failed: %s", _e)

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
        select(User).where(
            User.is_discoverable == True,  # noqa: E712
            User.is_remote == False,  # noqa: E712  Exclude ghost/remote users
        ).order_by(User.display_name)
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


class AgentUpdate(BaseModel):
    personality: str


@router.put("/users/{user_id}/agent", response_model=AgentResponse)
async def update_agent(user_id: str, data: AgentUpdate, db: AsyncSession = Depends(get_db),
                       auth_user_id: str = Depends(get_current_user_id)):
    """Update agent personality mode."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    result = await db.execute(select(Agent).where(Agent.owner_id == user_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")
    agent.personality = data.personality
    await db.commit()
    await db.refresh(agent)
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


@router.put("/users/{user_id}")
async def update_user_profile(user_id: str, request: Request, db: AsyncSession = Depends(get_db),
                              auth_user_id: str = Depends(get_current_user_id)):
    """Update user profile fields (is_discoverable, bio, display_name)."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    body = await request.json()
    if "is_discoverable" in body:
        user.is_discoverable = bool(body["is_discoverable"])
    if "bio" in body and isinstance(body["bio"], str):
        user.bio = body["bio"]
    if "display_name" in body and isinstance(body["display_name"], str):
        user.display_name = body["display_name"]
    if "email" in body:
        email_val = (body["email"] or "").strip().lower() or None
        if email_val:
            existing = await db.execute(select(User).where(User.email == email_val))
            existing_user = existing.scalar_one_or_none()
            if existing_user and existing_user.id != user_id:
                raise HTTPException(400, "Email already in use")
        user.email = email_val
    if "avatar_url" in body and isinstance(body["avatar_url"], str):
        # Accept base64 data URIs (max ~500KB) or external URLs
        avatar = body["avatar_url"]
        if avatar and len(avatar) > 512_000:
            raise HTTPException(400, "Avatar too large (max 500KB)")
        user.avatar_url = avatar or None

    await db.commit()
    await db.refresh(user)

    # Fire-and-forget registry sync when discoverability changes
    if "is_discoverable" in body:
        import asyncio
        from src.federation import register_with_registry, deregister_from_registry, POD_URL

        result = await db.execute(select(Agent).where(Agent.owner_id == user_id))
        agent = result.scalar_one_or_none()
        if agent:
            # Try to get private key for signed registration
            private_key = None
            if transit_bridge.has_key(user_id) and agent.encrypted_private_key:
                try:
                    private_key = transit_bridge.decrypt(user_id, agent.encrypted_private_key)
                except Exception:
                    pass

            if user.is_discoverable:
                asyncio.create_task(register_with_registry(
                    agent_did=agent.did,
                    agent_name=agent.name,
                    pod_url=POD_URL,
                    entity_type=user.user_type or "person",
                    username=user.username,
                    display_name=user.display_name or "",
                    bio=user.bio or "",
                    private_key_bytes=private_key,
                ))
            else:
                asyncio.create_task(deregister_from_registry(
                    agent_did=agent.did,
                    private_key_bytes=private_key,
                ))

    return UserResponse.model_validate(user).model_dump(mode="json")


@router.post("/users/{user_id}/claim-handle")
async def claim_handle(user_id: str, request: Request, db: AsyncSession = Depends(get_db),
                       auth_user_id: str = Depends(get_current_user_id)):
    """Claim a public handle (username) for Go Live. Checks registry uniqueness."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    body = await request.json()
    handle = body.get("handle", "").strip().lower()

    import re
    if not handle or not re.match(r'^[a-z0-9_-]{2,50}$', handle):
        raise HTTPException(400, "Handle must be 2-50 characters: lowercase letters, numbers, _ or -")
    if handle.startswith("remote:"):
        raise HTTPException(400, "Invalid handle")

    # Check local uniqueness
    existing = await db.execute(select(User).where(User.username == handle))
    existing_user = existing.scalar_one_or_none()
    if existing_user and existing_user.id != user_id:
        raise HTTPException(409, "Handle already taken")

    # Check registry uniqueness
    registry_url = os.getenv("TRUSTMESH_REGISTRY_URL", "")
    if registry_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{registry_url.rstrip('/')}/api/search?q={handle}")
                if r.status_code == 200:
                    results = r.json().get("results", [])
                    for agent in results:
                        if agent.get("username") == handle:
                            raise HTTPException(409, "Handle already taken in the public registry")
        except HTTPException:
            raise
        except Exception:
            pass  # Registry unreachable — allow local claim

    user.username = handle
    user.is_discoverable = True
    await db.commit()
    await db.refresh(user)

    # Register with public registry
    import asyncio
    from src.federation import register_with_registry, POD_URL

    result = await db.execute(select(Agent).where(Agent.owner_id == user_id))
    agent = result.scalar_one_or_none()
    if agent:
        private_key = None
        if transit_bridge.has_key(user_id) and agent.encrypted_private_key:
            try:
                private_key = transit_bridge.decrypt(user_id, agent.encrypted_private_key)
            except Exception:
                pass
        asyncio.create_task(register_with_registry(
            agent_did=agent.did,
            agent_name=agent.name,
            pod_url=POD_URL,
            entity_type=user.user_type or "person",
            username=handle,
            display_name=user.display_name or "",
            bio=user.bio or "",
            private_key_bytes=private_key,
        ))

    return UserResponse.model_validate(user).model_dump(mode="json")


@router.get("/users/{user_id}/check-handle")
async def check_handle(user_id: str, handle: str, db: AsyncSession = Depends(get_db)):
    """Check if a handle is available (local + registry)."""
    import re
    handle = handle.strip().lower()
    if not handle or not re.match(r'^[a-z0-9_-]{2,50}$', handle):
        return {"available": False, "reason": "Invalid format"}

    # Check local
    existing = await db.execute(select(User).where(User.username == handle))
    existing_user = existing.scalar_one_or_none()
    if existing_user and existing_user.id != user_id:
        return {"available": False, "reason": "Taken locally"}

    # Check registry
    registry_url = os.getenv("TRUSTMESH_REGISTRY_URL", "")
    if registry_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{registry_url.rstrip('/')}/api/search?q={handle}")
                if r.status_code == 200:
                    for agent in r.json().get("results", []):
                        if agent.get("username") == handle:
                            return {"available": False, "reason": "Taken in registry"}
        except Exception:
            pass

    return {"available": True}


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


@router.patch("/users/{user_id}/agent-mode")
async def patch_agent_mode(user_id: str, data: AgentModeUpdate, db: AsyncSession = Depends(get_db),
                            auth_user_id: str = Depends(get_current_user_id)):
    """Toggle org agent visibility between 'internal' and 'public'."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    if data.mode not in ("public", "internal"):
        raise HTTPException(400, "mode must be 'public' or 'internal'")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.user_type != "organization":
        raise HTTPException(400, "Only organization pods can change agent mode")
    user.agent_mode = data.mode
    user.is_discoverable = (data.mode == "public")
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user).model_dump(mode="json")

# PATCH /api/users/{id}/connectivity is handled by the Zig kernel (handlers/users.zig).
