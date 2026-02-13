"""Service agent routes — discovery, creation, and A2A agent cards."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import extract_profile
from src.crypto import derive_vault_key, encrypt, encrypt_text, generate_key, generate_ed25519_keypair, public_key_to_did, public_key_to_b64
from src.database import get_db
from src.embeddings import upsert_capsule_embedding
from src.models import Agent, CapsuleNetworkAccess, KnowledgeCapsule, User, parse_profile_data
from src.schemas import (
    AgentCard,
    AgentSkillSchema,
    ServiceCreate,
    ServiceResponse,
    UserPublic,
)

router = APIRouter(prefix="/api", tags=["services"])


def _build_agent_card(user: User, agent: Agent) -> AgentCard:
    """Build an A2A-compatible agent card for a user/service."""
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
        url=f"/api/users/{user.id}/agent/a2a",
        version="1.0.0",
        owner=UserPublic(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            bio=user.bio,
            user_type=user.user_type,
        ),
        public_key_b64=public_key_to_b64(agent.public_key) if agent.public_key else None,
        did=agent.did,
        capabilities=["knowledge-query", "trust-aware-sharing"]
        + (["quote-request", "availability-check"] if user.user_type == "service" else []),
        skills=skills,
    )


@router.get("/services", response_model=list[ServiceResponse])
async def list_services(db: AsyncSession = Depends(get_db)):
    """List all service provider agents with their cards."""
    result = await db.execute(
        select(User).where(User.user_type == "service").order_by(User.display_name)
    )
    services = []
    for user in result.scalars().all():
        agent_result = await db.execute(
            select(Agent).where(Agent.owner_id == user.id)
        )
        agent = agent_result.scalar_one_or_none()
        card = _build_agent_card(user, agent) if agent else None

        profile = parse_profile_data(user.profile_data)

        services.append(ServiceResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            bio=user.bio,
            user_type="service",
            profile_data=profile,
            agent_card=card,
        ))
    return services


@router.post("/services", response_model=ServiceResponse)
async def create_service(data: ServiceCreate, db: AsyncSession = Depends(get_db)):
    """Create a new service provider agent."""
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Username already taken")

    vault_master_key = generate_key()
    derived_key, salt = derive_vault_key(data.password)
    encrypted_vault_key = encrypt(vault_master_key, derived_key)

    # Extract profile from bio
    profile = await extract_profile(data.bio, data.display_name)

    user = User(
        username=data.username,
        display_name=data.display_name,
        bio=data.bio,
        user_type="service",
        profile_data=json.dumps(profile) if profile else None,
        is_discoverable=True,
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
        name=f"{data.display_name} Agent",
        personality=data.agent_personality or f"Professional {data.display_name} service agent",
        public_key=public_key_bytes,
        encrypted_private_key=encrypted_privkey,
        did=agent_did,
    )
    db.add(agent)
    await db.flush()

    # Store vault key
    from src.main import vault_keys
    vault_keys[user.id] = vault_master_key

    # Create capsules from provided data
    for capsule_data in data.capsules:
        capsule = KnowledgeCapsule(
            owner_id=user.id,
            capsule_type=capsule_data.get("type", "skill"),
            title=capsule_data.get("title", "Service Info"),
            content_encrypted=encrypt_text(capsule_data.get("content", ""), vault_master_key),
            tier=capsule_data.get("tier", "public"),
        )
        db.add(capsule)
        await db.flush()
        upsert_capsule_embedding(
            capsule.id,
            f"{capsule.title}: {capsule_data.get('content', '')}",
            {"capsule_id": capsule.id, "owner_id": user.id, "tier": capsule.tier},
        )

    await db.commit()
    await db.refresh(user)

    card = _build_agent_card(user, agent)
    return ServiceResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        bio=user.bio,
        user_type="service",
        profile_data=profile,
        agent_card=card,
    )
