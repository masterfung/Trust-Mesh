"""Agent registry routes — discovery, lookup, and search across the pod.

For hackathon demo, the registry is local (searches User/Agent tables on this pod).
In production, this would be a separate service aggregating agent cards from many pods.
"""

from fastapi import APIRouter, Query
from sqlalchemy import select

from src.database import async_session
from src.models import Agent, Network, NetworkMembership, User, parse_profile_data

router = APIRouter(prefix="/api/registry", tags=["registry"])


@router.get("/agents")
async def list_agents(
    discoverable_only: bool = True,
    user_type: str | None = None,
):
    """List all agents registered on this pod.

    By default only returns discoverable agents (is_discoverable=True).
    """
    async with async_session() as db:
        query = select(Agent, User).join(User, Agent.owner_id == User.id)
        if discoverable_only:
            query = query.where(User.is_discoverable == True)  # noqa: E712
        if user_type:
            types = [t.strip() for t in user_type.split(",")]
            query = query.where(User.user_type.in_(types))
        query = query.order_by(User.display_name)

        result = await db.execute(query)
        agents = []
        for agent, user in result.all():
            profile = parse_profile_data(user.profile_data) or {}
            # Get user's network memberships
            net_result = await db.execute(
                select(Network.name)
                .join(NetworkMembership, NetworkMembership.network_id == Network.id)
                .where(NetworkMembership.user_id == user.id)
            )
            pools = list(net_result.scalars().all())

            agents.append({
                "did": agent.did,
                "username": user.username,
                "display_name": user.display_name,
                "bio": user.bio,
                "user_type": user.user_type,
                "org_subtype": user.org_subtype,
                "profile_data": profile,
                "pools": pools,
                "skills": profile.get("skills", []),
                "is_discoverable": user.is_discoverable,
            })

        return {"agents": agents, "count": len(agents)}


@router.get("/search")
async def search_agents(
    q: str = Query(default="", description="Search query — matches name, bio, skills"),
    capability: str | None = Query(default=None, description="Filter by skill category"),
    user_type: str | None = Query(default=None, description="Filter by user type (person, organization, government)"),
):
    """Search for agents by capability, name, or description.

    Only returns discoverable agents. This is the public search API.
    """
    async with async_session() as db:
        query = (
            select(Agent, User)
            .join(User, Agent.owner_id == User.id)
            .where(User.is_discoverable == True)  # noqa: E712
        )
        if user_type:
            types = [t.strip() for t in user_type.split(",")]
            query = query.where(User.user_type.in_(types))
        query = query.order_by(User.display_name)

        result = await db.execute(query)
        agents = []
        q_lower = q.lower()

        for agent, user in result.all():
            profile = parse_profile_data(user.profile_data) or {}
            skills = profile.get("skills", [])

            # Text search: match against name, bio, skills
            searchable = f"{user.display_name} {user.bio} {user.username}".lower()
            for skill in skills:
                searchable += f" {skill.get('name', '')} {skill.get('category', '')}".lower()

            if q_lower and q_lower not in searchable:
                # Check individual words
                words = q_lower.split()
                if not any(w in searchable for w in words):
                    continue

            # Capability filter: match skill categories
            if capability:
                cap_lower = capability.lower()
                skill_categories = [s.get("category", "").lower() for s in skills]
                skill_names = [s.get("name", "").lower() for s in skills]
                if not any(cap_lower in c for c in skill_categories + skill_names):
                    continue

            # Get pools
            net_result = await db.execute(
                select(Network.name)
                .join(NetworkMembership, NetworkMembership.network_id == Network.id)
                .where(NetworkMembership.user_id == user.id)
            )
            pools = list(net_result.scalars().all())

            agents.append({
                "did": agent.did,
                "username": user.username,
                "display_name": user.display_name,
                "bio": user.bio,
                "user_type": user.user_type,
                "org_subtype": user.org_subtype,
                "skills": skills,
                "pools": pools,
            })

        return {"query": q, "results": agents, "count": len(agents)}


@router.get("/lookup/{did}")
async def lookup_agent(did: str):
    """Look up an agent by DID (Decentralized Identifier).

    Returns the agent's public info and pod location.
    This always works even for non-discoverable agents (DID is their address).
    """
    async with async_session() as db:
        result = await db.execute(
            select(Agent, User)
            .join(User, Agent.owner_id == User.id)
            .where(Agent.did == did)
        )
        row = result.first()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(404, f"No agent found with DID: {did}")

        agent, user = row
        profile = parse_profile_data(user.profile_data) or {}

        # Get pools
        net_result = await db.execute(
            select(Network.name)
            .join(NetworkMembership, NetworkMembership.network_id == Network.id)
            .where(NetworkMembership.user_id == user.id)
        )
        pools = list(net_result.scalars().all())

        from src.federation import POD_NAME, POD_URL
        return {
            "did": agent.did,
            "username": user.username,
            "display_name": user.display_name,
            "bio": user.bio,
            "user_type": user.user_type,
            "org_subtype": user.org_subtype,
            "profile_data": profile,
            "skills": profile.get("skills", []),
            "pools": pools,
            "is_discoverable": user.is_discoverable,
            "pod": {
                "name": POD_NAME,
                "url": POD_URL,
            },
        }
