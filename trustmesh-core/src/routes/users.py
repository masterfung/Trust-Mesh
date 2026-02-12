"""User signup, profile, and discovery routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.crypto import derive_vault_key, encrypt, generate_key
from src.database import get_db
from src.models import Agent, User
from src.schemas import AgentCard, AgentResponse, UserCreate, UserPublic, UserResponse

router = APIRouter(prefix="/api", tags=["users"])


@router.post("/users", response_model=UserResponse)
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Create a new user with vault and personal agent."""
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
