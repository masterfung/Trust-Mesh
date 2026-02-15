"""Opus 4.6 personal agent logic — the core intelligence layer.

Agents have two modes:
- Cross-query (read-only): Another user asks your agent. Agent reasons about
  what to share based on trust level. No tools.
- Self-query (tool-enabled): You talk to your own agent. Agent can search your
  vault, create capsules, update capsules. Smart dedup via search-before-save.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.model_router import get_router
from src.models import Agent, AgentTask, KnowledgeCapsule, Network, Notification

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Tool Definitions (for self-query mode)
# ═══════════════════════════════════════════════════════════════

AGENT_TOOLS = [
    {
        "name": "search_vault",
        "description": (
            "Search the owner's knowledge vault for existing capsules related to a topic. "
            "ALWAYS call this before saving new information to check for duplicates or "
            "existing capsules that should be updated instead of creating new ones."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find related capsules (e.g., 'Peter allergies', 'grandma medications', 'work schedule')",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "save_capsule",
        "description": (
            "Save new knowledge to the vault OR update an existing capsule. "
            "If existing_capsule_id is provided, updates that capsule (replaces content). "
            "Otherwise creates a new capsule. The agent should intelligently classify "
            "the type, tier, category, and freshness based on the content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "Short descriptive title. Include the person's name if the info is "
                        "about someone else (e.g., \"Peter's Shellfish Allergy\", "
                        "\"Grandma Rose's Medications\")"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "The knowledge content to save. Be clear and specific.",
                },
                "capsule_type": {
                    "type": "string",
                    "enum": ["memory", "skill", "procedure", "schedule", "preference", "contact"],
                    "description": (
                        "Type: memory (events/observations), skill (expertise/how-to), "
                        "procedure (step-by-step instructions), schedule (time-based events), "
                        "preference (likes, dislikes, allergies, dietary — note: 'hate' = dislike, NOT allergy), "
                        "contact (people/phone/email)"
                    ),
                },
                "visibility": {
                    "type": "string",
                    "enum": ["private", "internal", "shareable", "open"],
                    "description": (
                        "Visibility level: "
                        "private (owner only — diary entries, secrets), "
                        "internal (owner + trusted networks — family health info, work data), "
                        "shareable (explicitly shared with specific people, has expiry), "
                        "open (discoverable by anyone — professional bio). "
                        "Use category defaults: health→internal, personal→private, work→internal, general→open."
                    ),
                },
                "emergency_accessible": {
                    "type": "boolean",
                    "description": (
                        "Can verified healthcare providers access this via emergency UCAN tokens? "
                        "Default true for health category (allergies, medications, conditions). "
                        "Default false for everything else. Owner can override."
                    ),
                },
                "can_reshare": {
                    "type": "boolean",
                    "description": (
                        "Can someone who views this data share it with others? "
                        "Default false for health/personal, true for open/general. "
                        "When false, viewing agents say 'This is shared for your reference only.'"
                    ),
                },
                "category": {
                    "type": "string",
                    "enum": ["health", "home", "work", "personal", "family", "general"],
                    "description": (
                        "Category: health (actual medical conditions, allergies, medications), "
                        "home (house/property), work (professional), personal (hobbies, dislikes, preferences), "
                        "family (family events/info), general (other). "
                        "IMPORTANT: food dislikes are 'personal', NOT 'health'. Only real allergies are 'health'."
                    ),
                },
                "freshness": {
                    "type": "string",
                    "enum": ["permanent", "temporary", "recurring"],
                    "description": (
                        "permanent (facts, skills — doesn't change), "
                        "temporary (events, locations — may expire), "
                        "recurring (schedules, routines — repeats)"
                    ),
                },
                "network_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Names of networks to share with (for network tier). "
                        "Must match exact network names from the owner's networks list."
                    ),
                },
                "existing_capsule_id": {
                    "type": "string",
                    "description": (
                        "If updating an existing capsule instead of creating new, provide its ID. "
                        "The content will REPLACE the old content. Use this when search_vault found "
                        "a related capsule that should be updated rather than duplicated."
                    ),
                },
            },
            "required": ["title", "content", "capsule_type", "visibility", "category", "freshness"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Search the web for real, current information. Use for finding services, "
            "prices, reviews, or any external data not in the vault."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "context": {
                    "type": "string",
                    "description": "Why you're searching — helps refine results",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_task",
        "description": (
            "Create a trackable task for multi-step work. Use when research or "
            "comparison involves multiple steps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task title"},
                "description": {"type": "string", "description": "What needs to be done"},
                "task_type": {
                    "type": "string",
                    "enum": ["search", "compare", "compile", "follow_up"],
                    "description": "Type of task",
                },
            },
            "required": ["title", "description", "task_type"],
        },
    },
    {
        "name": "query_peer",
        "description": (
            "Ask another user's or service's agent a question. Trust rules apply — "
            "you can only get information your owner has access to."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_username": {
                    "type": "string",
                    "description": "Username of the person or service to query",
                },
                "question": {
                    "type": "string",
                    "description": "The question to ask their agent",
                },
                "reason": {
                    "type": "string",
                    "description": "Why you're asking — helps with context",
                },
            },
            "required": ["target_username", "question"],
        },
    },
    {
        "name": "request_quotes",
        "description": (
            "Send a quote request to service providers in the mesh. "
            "Returns structured quotes for comparison."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service_type": {
                    "type": "string",
                    "description": "Type of service: 'cleaning', 'tutoring', 'handyman', etc.",
                },
                "requirements": {
                    "type": "string",
                    "description": "Detailed requirements for the quote",
                },
                "budget_hint": {
                    "type": "string",
                    "description": "Optional budget range",
                },
            },
            "required": ["service_type", "requirements"],
        },
    },
    {
        "name": "discover_agents",
        "description": (
            "Discover agents across the pod and federation by capability, specialty, or name. "
            "Returns agents with their trust level relative to the owner, pool membership, and skills. "
            "Use this when looking for specialists (doctors, tutors, services), people in specific pools, "
            "or to find who can help with a particular need. More powerful than list_connections — "
            "this searches ALL discoverable agents, not just direct connections."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — matches name, bio, skills (e.g., 'doctor', 'cleaning service', 'tutor')",
                },
                "capability": {
                    "type": "string",
                    "description": "Filter by skill category (e.g., 'medical', 'professional', 'education')",
                },
                "user_type": {
                    "type": "string",
                    "enum": ["person", "organization", "government"],
                    "description": "Filter by entity type",
                },
            },
        },
    },
    {
        "name": "list_connections",
        "description": (
            "List the owner's connections and their trust levels. "
            "Use this to know who you can query_peer and what networks you share. "
            "Call this BEFORE query_peer if you're unsure who to ask."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_services",
        "description": (
            "List available service providers in the mesh with their skills and descriptions. "
            "Use before request_quotes to know what services are available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "discover_networks",
        "description": (
            "Discover public networks/groups the owner can join (music groups, neighborhood, "
            "hobby clubs, professional networks). Use when the owner asks about joining groups, "
            "communities, or social circles."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "interest": {
                    "type": "string",
                    "description": "Optional interest filter (e.g., 'music', 'dance', 'coding', 'sports')",
                },
            },
        },
    },
    {
        "name": "check_calendar",
        "description": (
            "Check the owner's calendar for upcoming events. "
            "Use when asked about schedule, appointments, meetings, or 'what's on my calendar'. "
            "Returns events for the requested time range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "time_range": {
                    "type": "string",
                    "enum": ["today", "tomorrow", "this_week", "next_week"],
                    "description": "Time range to check. Default: 'this_week'.",
                },
            },
        },
    },
    {
        "name": "draft_email",
        "description": (
            "Draft an email and save it as a capsule. Use when the owner asks to "
            "compose, draft, or write an email to someone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient name or email",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body content",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
]


# ═══════════════════════════════════════════════════════════════
# Tool Context (passed to tool handlers)
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolContext:
    """Everything the agent's tools need to execute."""
    db: object  # AsyncSession — typed as object to avoid import cycle
    vault_key: bytes
    owner_id: str
    owner_name: str
    networks: list[dict]  # [{id, name, network_type}]
    actions: list[dict] = field(default_factory=list)
    query_depth: int = 0  # Recursion guard for query_peer


# ═══════════════════════════════════════════════════════════════
# Tool Handlers
# ═══════════════════════════════════════════════════════════════

async def handle_search_vault(ctx: ToolContext, query: str) -> str:
    """Search the vault for capsules matching the query. Returns JSON summary."""
    from src.crypto import decrypt_text
    from src.embeddings import search_capsules

    from sqlalchemy import select

    # Get ALL capsule IDs for the owner (self-query = private access)
    result = await ctx.db.execute(
        select(KnowledgeCapsule.id).where(
            KnowledgeCapsule.owner_id == ctx.owner_id,
            KnowledgeCapsule.is_archived == False,  # noqa: E712
        )
    )
    all_ids = list(result.scalars().all())

    if not all_ids:
        return json.dumps({"found": 0, "capsules": [], "message": "Vault is empty."})

    # Semantic search
    matched_ids = search_capsules(query, all_ids, top_k=5)
    if not matched_ids:
        return json.dumps({"found": 0, "capsules": [], "message": "No matching capsules found."})

    # Load and decrypt matches
    result = await ctx.db.execute(
        select(KnowledgeCapsule).where(KnowledgeCapsule.id.in_(matched_ids))
    )
    capsules = result.scalars().all()

    matches = []
    for c in capsules:
        try:
            content = decrypt_text(c.content_encrypted, ctx.vault_key)
        except Exception:
            content = "[Could not decrypt]"
        matches.append({
            "id": c.id,
            "title": c.title,
            "capsule_type": c.capsule_type,
            "visibility": c.visibility,
            "emergency_accessible": c.emergency_accessible,
            "category": c.category,
            "content": content[:500],  # Truncate for context window
        })

    return json.dumps({
        "found": len(matches),
        "capsules": matches,
        "message": f"Found {len(matches)} related capsule(s). Review them to decide whether to update an existing one or create new.",
    })


async def handle_save_capsule(ctx: ToolContext, params: dict) -> str:
    """Create or update a capsule in the vault. Returns confirmation JSON."""
    from src.crypto import content_hash, encrypt_text
    from src.embeddings import upsert_capsule_embedding
    from src.models import CapsuleNetworkAccess

    from sqlalchemy import select

    title = params["title"]
    content = params["content"]
    capsule_type = params["capsule_type"]
    # Support both old "tier" and new "visibility" from agent
    visibility = params.get("visibility") or params.get("tier", "private")
    # Map old tier names to new visibility names
    tier_to_vis = {"public": "open", "network": "internal", "private": "private"}
    visibility = tier_to_vis.get(visibility, visibility)
    emergency_accessible = params.get("emergency_accessible", False)
    can_reshare = params.get("can_reshare", False)
    category = params["category"]
    freshness = params["freshness"]
    network_names = params.get("network_names", [])
    existing_id = params.get("existing_capsule_id")

    # Apply category defaults if not explicitly set
    if category == "health" and not params.get("emergency_accessible"):
        emergency_accessible = True
    if visibility == "open" and not params.get("can_reshare"):
        can_reshare = True

    # Resolve network names to IDs
    network_ids = []
    resolved_network_names = []
    for name in network_names:
        for net in ctx.networks:
            if net["name"].lower() == name.lower():
                network_ids.append(net["id"])
                resolved_network_names.append(net["name"])
                break

    # If internal but no networks specified, default to first network
    if visibility == "internal" and not network_ids and ctx.networks:
        network_ids = [ctx.networks[0]["id"]]
        resolved_network_names = [ctx.networks[0]["name"]]

    if existing_id:
        # UPDATE existing capsule
        capsule = await ctx.db.get(KnowledgeCapsule, existing_id)
        if not capsule or capsule.owner_id != ctx.owner_id:
            return json.dumps({"success": False, "error": "Capsule not found or not owned by you."})

        old_title = capsule.title
        capsule.title = title
        capsule.content_encrypted = encrypt_text(content, ctx.vault_key)
        capsule.content_hash = content_hash(content)
        capsule.capsule_type = capsule_type
        capsule.visibility = visibility
        capsule.emergency_accessible = emergency_accessible
        capsule.can_reshare = can_reshare
        capsule.category = category
        capsule.freshness = freshness

        # Update network access
        existing_na = await ctx.db.execute(
            select(CapsuleNetworkAccess).where(CapsuleNetworkAccess.capsule_id == existing_id)
        )
        for na in existing_na.scalars().all():
            await ctx.db.delete(na)
        for nid in network_ids:
            ctx.db.add(CapsuleNetworkAccess(capsule_id=existing_id, network_id=nid))

        await ctx.db.flush()

        # Re-embed
        upsert_capsule_embedding(
            capsule.id,
            f"{title}: {content}",
            {"capsule_id": capsule.id, "owner_id": ctx.owner_id, "visibility": visibility},
        )

        action = {
            "type": "capsule_updated",
            "capsule_id": capsule.id,
            "title": title,
            "old_title": old_title,
            "capsule_type": capsule_type,
            "visibility": visibility,
            "emergency_accessible": emergency_accessible,
            "category": category,
            "networks": resolved_network_names,
        }
        ctx.actions.append(action)

        return json.dumps({
            "success": True,
            "action": "updated",
            "capsule_id": capsule.id,
            "title": title,
            "message": f"Updated capsule '{title}' ({capsule_type}, {visibility}, {category})",
        })
    else:
        # CREATE new capsule
        capsule = KnowledgeCapsule(
            owner_id=ctx.owner_id,
            capsule_type=capsule_type,
            title=title,
            content_encrypted=encrypt_text(content, ctx.vault_key),
            content_hash=content_hash(content),
            visibility=visibility,
            emergency_accessible=emergency_accessible,
            can_reshare=can_reshare,
            category=category,
            freshness=freshness,
        )
        ctx.db.add(capsule)
        await ctx.db.flush()

        # Add network access
        for nid in network_ids:
            ctx.db.add(CapsuleNetworkAccess(capsule_id=capsule.id, network_id=nid))

        await ctx.db.flush()

        # Embed for semantic search
        upsert_capsule_embedding(
            capsule.id,
            f"{title}: {content}",
            {"capsule_id": capsule.id, "owner_id": ctx.owner_id, "visibility": visibility},
        )

        # Build governance summary for confirmation
        gov_notes = []
        if emergency_accessible:
            gov_notes.append("emergency-accessible")
        if can_reshare:
            gov_notes.append("reshare-allowed")
        gov_str = f" [{', '.join(gov_notes)}]" if gov_notes else ""

        action = {
            "type": "capsule_created",
            "capsule_id": capsule.id,
            "title": title,
            "capsule_type": capsule_type,
            "visibility": visibility,
            "emergency_accessible": emergency_accessible,
            "can_reshare": can_reshare,
            "category": category,
            "networks": resolved_network_names,
        }
        ctx.actions.append(action)

        return json.dumps({
            "success": True,
            "action": "created",
            "capsule_id": capsule.id,
            "title": title,
            "message": f"Created capsule '{title}' ({capsule_type}, {visibility}, {category}){gov_str}"
                       + (f" shared with {', '.join(resolved_network_names)}" if resolved_network_names else ""),
        })


async def handle_web_search(ctx: ToolContext, query: str, context: str = "") -> str:
    """Search the web via Tavily API. Returns top results."""
    try:
        from tavily import TavilyClient
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            return json.dumps({
                "success": False,
                "error": "Web search unavailable (no API key configured)",
                "results": [],
            })
        client = TavilyClient(api_key=api_key)
        response = client.search(query=query, max_results=5)
        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:300],
            })
        return json.dumps({
            "success": True,
            "query": query,
            "results": results,
            "result_count": len(results),
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e), "results": []})


async def handle_create_task(ctx: ToolContext, params: dict) -> str:
    """Create a trackable agent task."""
    from sqlalchemy import select

    task = AgentTask(
        owner_id=ctx.owner_id,
        title=params["title"],
        description=params["description"],
        task_type=params["task_type"],
        status="in_progress",
    )
    ctx.db.add(task)
    await ctx.db.flush()

    ctx.actions.append({
        "type": "task_created",
        "task_id": task.id,
        "title": task.title,
        "task_type": task.task_type,
    })

    return json.dumps({
        "success": True,
        "task_id": task.id,
        "title": task.title,
        "message": f"Created task: {task.title}",
    })


async def handle_discover_agents(ctx: ToolContext, params: dict) -> str:
    """Discover agents by capability, name, or type. Returns agents with trust levels."""
    from sqlalchemy import select
    from src.models import User, Connection, NetworkMembership
    from src.trust import resolve_trust_level
    from src.models import parse_profile_data

    query_text = params.get("query", "").lower()
    capability = params.get("capability", "").lower()
    user_type_filter = params.get("user_type")

    # Build query for discoverable users (exclude self)
    stmt = (
        select(User)
        .where(User.is_discoverable == True)  # noqa: E712
        .where(User.id != ctx.owner_id)
        .order_by(User.display_name)
    )
    if user_type_filter:
        types = [user_type_filter]
        if user_type_filter == "organization":
            types.append("service")  # backward compat
        stmt = stmt.where(User.user_type.in_(types))

    result = await ctx.db.execute(stmt)
    users = result.scalars().all()

    agents = []
    for user in users:
        profile = parse_profile_data(user.profile_data) or {}
        skills = profile.get("skills", [])

        # Text search filter
        if query_text:
            searchable = f"{user.display_name} {user.bio} {user.username}".lower()
            for skill in skills:
                searchable += f" {skill.get('name', '')} {skill.get('category', '')}".lower()
            words = query_text.split()
            if not any(w in searchable for w in words):
                continue

        # Capability filter
        if capability:
            skill_cats = [s.get("category", "").lower() for s in skills]
            skill_names = [s.get("name", "").lower() for s in skills]
            if not any(capability in c for c in skill_cats + skill_names):
                continue

        # Resolve trust level
        trust_level, shared_nets = await resolve_trust_level(ctx.db, ctx.owner_id, user.id)
        network_names = [n.name for n in shared_nets]

        # Get pool memberships (only show public networks to prevent leaking private pool info)
        net_result = await ctx.db.execute(
            select(Network.name)
            .join(NetworkMembership, NetworkMembership.network_id == Network.id)
            .where(
                NetworkMembership.user_id == user.id,
                Network.is_public == True,  # noqa: E712
            )
        )
        pools = list(net_result.scalars().all())

        agents.append({
            "username": user.username,
            "display_name": user.display_name,
            "bio": user.bio[:200],
            "user_type": user.user_type,
            "trust_level": trust_level,
            "shared_networks": network_names,
            "pools": pools,
            "skills": [{"name": s.get("name", ""), "category": s.get("category", "")} for s in skills[:5]],
            "recommended": trust_level == "network",
        })

    # Sort: recommended (pool-sharing) agents first, then alphabetically
    agents.sort(key=lambda a: (not a["recommended"], a["display_name"]))

    ctx.actions.append({
        "type": "agents_discovered",
        "query": query_text or capability or user_type_filter or "all",
        "results_count": len(agents),
    })

    return json.dumps({
        "success": True,
        "agents": agents[:20],  # Limit to top 20
        "total": len(agents),
        "tip": "Agents marked 'recommended' share pools with you and will share more. Use query_peer to ask any agent a question.",
    })


MAX_QUERY_DEPTH = 2  # Prevent infinite agent-to-agent recursion


async def handle_query_peer(ctx: ToolContext, params: dict) -> str:
    """Query another user's agent. Full trust pipeline enforced.

    Three-path lookup:
    1. Local real user — fast path via local gossip
    2. Ghost user (is_remote=True) — route through federation to their real pod
    3. Peer fallback — try each connected peer pod
    """
    if ctx.query_depth >= MAX_QUERY_DEPTH:
        return json.dumps({"success": False, "error": "Query depth limit reached — cannot nest further agent queries."})

    from sqlalchemy import select
    from src.models import Agent, PeerPod, User

    target_username = params["target_username"]
    question = params["question"]

    # Resolve username to user_id
    result = await ctx.db.execute(
        select(User).where(User.username == target_username)
    )
    target_user = result.scalar_one_or_none()

    # ── Path 1: Local real user (unchanged fast path) ──
    if target_user and not target_user.is_remote:
        from src.gossip import query_agent
        from src.main import vault_keys

        query_result = await query_agent(
            db=ctx.db,
            from_user_id=ctx.owner_id,
            to_user_id=target_user.id,
            question=question,
            vault_keys=vault_keys,
            query_depth=ctx.query_depth + 1,
        )

        ctx.actions.append({
            "type": "peer_queried",
            "target_username": target_username,
            "question": question[:100],
            "decision": query_result.get("decision", "unknown"),
        })

        trust_level = query_result.get("trust_level", "unknown")
        trust_explanation = {
            "private": "Full access (self-query)",
            "network": f"Trusted — you share networks: {', '.join(query_result.get('shared_networks', []))}",
            "connected": "Connected — you have a direct connection but no shared pools. Only open information visible, but they know who you are.",
            "public": "Limited access — only public/open information visible. Connect with them or join a shared pool for more access.",
        }.get(trust_level, "Unknown trust level")

        return json.dumps({
            "success": True,
            "target": target_username,
            "target_display_name": target_user.display_name,
            "target_type": target_user.user_type,
            "trust_level": trust_level,
            "trust_explanation": trust_explanation,
            "shared_networks": query_result.get("shared_networks", []),
            "response": query_result.get("response", "No response"),
            "decision": query_result.get("decision", "unknown"),
        })

    # ── Path 2: Ghost user — route through federation ──
    if target_user and target_user.is_remote:
        from src.federation import remote_query

        # Get our agent's DID
        agent_result = await ctx.db.execute(
            select(Agent).where(Agent.owner_id == ctx.owner_id)
        )
        our_agent = agent_result.scalar_one_or_none()
        our_did = our_agent.did if our_agent else "unknown"
        signing_key: bytes | None = None
        if our_agent and our_agent.encrypted_private_key:
            from src.crypto import decrypt
            try:
                signing_key = decrypt(our_agent.encrypted_private_key, ctx.vault_key)
            except Exception:
                signing_key = None

        # Extract real username from ghost format "remote:username@host"
        real_username = target_username
        if real_username.startswith("remote:"):
            real_username = real_username[7:]  # strip "remote:"
            if "@" in real_username:
                real_username = real_username.split("@")[0]

        remote_result = await remote_query(
            target_user.remote_pod_url, our_did, real_username, question, signing_private_key=signing_key
        )

        ctx.actions.append({
            "type": "peer_queried",
            "target_username": target_username,
            "question": question[:100],
            "decision": remote_result.get("decision", "unknown") if remote_result else "unreachable",
            "federated": True,
            "remote_pod": target_user.remote_pod_url,
        })

        if remote_result:
            return json.dumps({
                "success": True,
                "target": target_username,
                "target_display_name": target_user.display_name,
                "target_type": target_user.user_type,
                "trust_level": remote_result.get("trust_level", "public"),
                "trust_explanation": f"Federated query to {target_user.remote_pod_url}",
                "shared_networks": remote_result.get("shared_networks", []),
                "response": remote_result.get("response", "No response"),
                "decision": remote_result.get("decision", "unknown"),
                "federated": True,
                "remote_pod": target_user.remote_pod_url,
            })
        return json.dumps({
            "success": False,
            "error": f"Remote pod {target_user.remote_pod_url} is unreachable",
            "federated": True,
        })

    # ── Path 3: Peer fallback — user not found locally, try peers ──
    from src.federation import remote_query

    agent_result = await ctx.db.execute(
        select(Agent).where(Agent.owner_id == ctx.owner_id)
    )
    our_agent = agent_result.scalar_one_or_none()
    our_did = our_agent.did if our_agent else "unknown"
    signing_key: bytes | None = None
    if our_agent and our_agent.encrypted_private_key:
        from src.crypto import decrypt
        try:
            signing_key = decrypt(our_agent.encrypted_private_key, ctx.vault_key)
        except Exception:
            signing_key = None

    peers_result = await ctx.db.execute(
        select(PeerPod).where(PeerPod.status == "active")
    )
    peers = peers_result.scalars().all()

    for peer in peers:
        remote_result = await remote_query(peer.url, our_did, target_username, question, signing_private_key=signing_key)
        if remote_result:
            ctx.actions.append({
                "type": "peer_queried",
                "target_username": target_username,
                "question": question[:100],
                "decision": remote_result.get("decision", "unknown"),
                "federated": True,
                "remote_pod": peer.url,
            })
            return json.dumps({
                "success": True,
                "target": target_username,
                "target_display_name": target_username,  # Don't know display name for remote
                "target_type": "unknown",
                "trust_level": remote_result.get("trust_level", "public"),
                "trust_explanation": f"Federated query to {peer.url} (public trust — no pool relationship)",
                "shared_networks": [],
                "response": remote_result.get("response", "No response"),
                "decision": remote_result.get("decision", "unknown"),
                "federated": True,
                "remote_pod": peer.url,
            })

    return json.dumps({
        "success": False,
        "error": f"User '{target_username}' not found locally or on any connected peer pod",
    })


async def handle_request_quotes(ctx: ToolContext, params: dict) -> str:
    """Request quotes from service providers matching the service type."""
    from sqlalchemy import select
    from src.models import User
    from src.gossip import query_agent
    from src.main import vault_keys

    service_type = params["service_type"]
    requirements = params["requirements"]
    budget_hint = params.get("budget_hint", "")

    # Find service agents matching the type
    result = await ctx.db.execute(
        select(User).where(User.user_type.in_(["service", "organization"]))
    )
    service_users = result.scalars().all()

    # Filter by relevance to service_type (check bio/name for keywords)
    keywords = service_type.lower().split()
    matching_services = []
    for su in service_users:
        text = f"{su.display_name} {su.bio}".lower()
        if any(kw in text for kw in keywords):
            matching_services.append(su)

    if not matching_services:
        # Also do a web search as fallback
        web_results = await handle_web_search(ctx, f"{service_type} services near me {requirements}")
        return json.dumps({
            "success": True,
            "mesh_quotes": [],
            "web_results": json.loads(web_results).get("results", []),
            "message": f"No {service_type} providers in the mesh. Found web results instead.",
        })

    # Query each matching service agent
    quotes = []
    for service in matching_services:
        quote_question = (
            f"I need a quote for: {requirements}."
            + (f" Budget: {budget_hint}." if budget_hint else "")
            + " Please provide pricing details, availability, and any relevant info."
        )
        try:
            qr = await query_agent(
                db=ctx.db,
                from_user_id=ctx.owner_id,
                to_user_id=service.id,
                question=quote_question,
                vault_keys=vault_keys,
            )
            quotes.append({
                "provider": service.display_name,
                "username": service.username,
                "response": qr.get("response", "No response"),
                "trust_level": qr.get("trust_level", "public"),
                "in_mesh": True,
            })

            # Notification for service owner
            notification = Notification(
                user_id=service.id,
                notification_type="quote_received",
                title=f"Quote request from {ctx.owner_name}",
                body=f"Service: {service_type}. Requirements: {requirements[:200]}",
                related_id=qr.get("id"),
            )
            ctx.db.add(notification)
        except Exception as e:
            log.warning(f"Quote request to {service.username} failed: {e}")
            quotes.append({
                "provider": service.display_name,
                "username": service.username,
                "response": "Unable to get quote from this provider at the moment.",
                "in_mesh": True,
            })

    await ctx.db.flush()

    ctx.actions.append({
        "type": "quotes_requested",
        "service_type": service_type,
        "providers_queried": len(quotes),
    })

    return json.dumps({
        "success": True,
        "mesh_quotes": quotes,
        "message": f"Got quotes from {len(quotes)} in-mesh provider(s).",
    })


async def handle_list_connections(ctx: ToolContext) -> str:
    """List the owner's connections with trust info."""
    from sqlalchemy import select, or_
    from src.models import Connection, NetworkMembership, User

    result = await ctx.db.execute(
        select(Connection).where(
            or_(Connection.from_user_id == ctx.owner_id, Connection.to_user_id == ctx.owner_id)
        )
    )
    # Build a set of network IDs the owner belongs to (from ctx.networks dicts)
    my_network_ids = {n["id"] for n in ctx.networks} if ctx.networks else set()

    connections = []
    for c in result.scalars().all():
        other_id = c.to_user_id if c.from_user_id == ctx.owner_id else c.from_user_id
        other = await ctx.db.get(User, other_id)
        if other:
            # Find shared networks by checking the other user's memberships
            shared_nets = []
            if my_network_ids:
                mem_result = await ctx.db.execute(
                    select(NetworkMembership.network_id).where(
                        NetworkMembership.user_id == other_id,
                        NetworkMembership.network_id.in_(my_network_ids),
                    )
                )
                shared_net_ids = set(mem_result.scalars().all())
                shared_nets = [n["name"] for n in ctx.networks if n["id"] in shared_net_ids]
            is_from = c.from_user_id == ctx.owner_id
            my_label = c.from_label if is_from else c.to_label
            connections.append({
                "username": other.username,
                "display_name": other.display_name,
                "user_type": other.user_type or "person",
                "relationship_type": c.relationship_type,
                "my_label": my_label,
                "shared_networks": shared_nets,
            })
    return json.dumps({"connections": connections, "count": len(connections)})


async def handle_list_services(ctx: ToolContext) -> str:
    """List available service providers in the mesh."""
    from sqlalchemy import select
    from src.models import User

    result = await ctx.db.execute(
        select(User).where(User.user_type.in_(["service", "organization"]))
    )
    services = []
    for s in result.scalars().all():
        # profile_data is stored as a JSON string in the Text column
        from src.models import parse_profile_data
        profile = parse_profile_data(s.profile_data) or {}
        services.append({
            "username": s.username,
            "display_name": s.display_name,
            "bio": s.bio,
            "skills": profile.get("skills", []),
        })
    return json.dumps({"services": services, "count": len(services)})


async def handle_discover_networks(ctx: ToolContext, interest: str = "") -> str:
    """Discover public networks the owner can join."""
    from sqlalchemy import func, select
    from src.models import Network, NetworkMembership, User

    # Get networks the owner already belongs to
    my_nets = await ctx.db.execute(
        select(NetworkMembership.network_id).where(NetworkMembership.user_id == ctx.owner_id)
    )
    my_network_ids = set(my_nets.scalars().all())

    # Get all public networks
    result = await ctx.db.execute(
        select(Network).where(Network.is_public == True).order_by(Network.name)  # noqa: E712
    )
    networks = result.scalars().all()

    discoverable = []
    for n in networks:
        if n.id in my_network_ids:
            continue  # Skip networks owner already belongs to
        # Filter by interest if provided
        if interest:
            text = f"{n.name} {n.description} {n.network_type}".lower()
            if not any(kw in text for kw in interest.lower().split()):
                continue
        # Get member count
        mem_count_result = await ctx.db.execute(
            select(func.count(NetworkMembership.id)).where(NetworkMembership.network_id == n.id)
        )
        member_count = mem_count_result.scalar() or 0
        owner = await ctx.db.get(User, n.owner_id)
        discoverable.append({
            "id": n.id,
            "name": n.name,
            "description": n.description,
            "network_type": n.network_type,
            "join_policy": n.join_policy,
            "member_count": member_count,
            "owner": owner.display_name if owner else "Unknown",
        })

    if not discoverable:
        return json.dumps({
            "networks": [],
            "message": f"No public networks found{' matching ' + repr(interest) if interest else ''}. The owner could create their own!",
        })

    return json.dumps({
        "networks": discoverable,
        "count": len(discoverable),
        "message": f"Found {len(discoverable)} public network(s) the owner can join.",
    })


# ═══════════════════════════════════════════════════════════════
# Mock Calendar & Email (same interface real OAuth/MCP would use)
# ═══════════════════════════════════════════════════════════════

MOCK_CALENDARS: dict[str, list[dict]] = {
    "molly": [
        {"time": "9:00 AM", "title": "Team Standup", "location": "Zoom", "day": "today", "recurring": True},
        {"time": "11:00 AM", "title": "1:1 with Kyle", "location": "Conference Room B", "day": "today"},
        {"time": "2:00 PM", "title": "Q4 Planning Review", "location": "Main Board Room", "day": "today"},
        {"time": "6:00 PM", "title": "Pick up Jane from soccer", "location": "Roosevelt Field", "day": "today"},
        {"time": "10:00 AM", "title": "Sprint Retrospective", "location": "Zoom", "day": "tomorrow"},
        {"time": "3:00 PM", "title": "Dentist — Jane", "location": "Dr. Kim's Office", "day": "tomorrow"},
        {"time": "All day", "title": "Flight to Austin — SRE Conference", "location": "SFO → AUS", "day": "this_week"},
        {"time": "7:00 PM", "title": "Visit Grandma Rose", "location": "Sunrise Assisted Living", "day": "this_week"},
    ],
    "peter": [
        {"time": "8:30 AM", "title": "Client Sync — Martinez Account", "location": "Office", "day": "today"},
        {"time": "12:00 PM", "title": "Lunch with Bill", "location": "Tony's Deli", "day": "today"},
        {"time": "4:00 PM", "title": "Jane's Piano Recital", "location": "Roosevelt Middle School", "day": "this_week"},
        {"time": "9:00 AM", "title": "Quarterly Review Prep", "location": "Home Office", "day": "tomorrow"},
        {"time": "6:30 PM", "title": "Dinner at Mom's", "location": "Sunrise Assisted Living", "day": "this_week"},
    ],
    "jane": [
        {"time": "3:30 PM", "title": "Soccer Practice", "location": "Roosevelt Field", "day": "today", "recurring": True},
        {"time": "4:00 PM", "title": "Piano Lesson", "location": "Ms. Chen's Studio", "day": "tomorrow"},
        {"time": "10:00 AM", "title": "SAT Practice Test", "location": "AceTutor Center", "day": "this_week"},
        {"time": "2:00 PM", "title": "Study Group — History", "location": "Library", "day": "this_week"},
    ],
    "bill": [
        {"time": "10:00 AM", "title": "Guitar Practice", "location": "Home", "day": "today"},
        {"time": "2:00 PM", "title": "Coding Club", "location": "School Lab", "day": "today", "recurring": True},
        {"time": "11:00 AM", "title": "Basketball Game", "location": "Community Center", "day": "this_week"},
    ],
    "dorothy": [
        {"time": "9:00 AM", "title": "Physical Therapy", "location": "Sunrise Wellness Center", "day": "today"},
        {"time": "11:00 AM", "title": "Bridge Club", "location": "Community Room", "day": "today", "recurring": True},
        {"time": "2:00 PM", "title": "Video Call with Harold", "location": "Room 204", "day": "tomorrow"},
        {"time": "10:00 AM", "title": "Dr. Patel — Checkup", "location": "Riverside General", "day": "this_week"},
    ],
    "kyle": [
        {"time": "9:00 AM", "title": "Team Standup", "location": "Zoom", "day": "today", "recurring": True},
        {"time": "11:00 AM", "title": "1:1 with Molly", "location": "Conference Room B", "day": "today"},
        {"time": "2:00 PM", "title": "Architecture Review — Auth Service", "location": "Zoom", "day": "tomorrow"},
        {"time": "5:00 PM", "title": "Board Game Night", "location": "Kyle's Place", "day": "this_week"},
    ],
}


async def handle_check_calendar(ctx: ToolContext, time_range: str = "this_week") -> str:
    """Return mock calendar events for the owner."""
    # Find the owner's username
    from sqlalchemy import select
    from src.models import User
    user = await ctx.db.execute(select(User.username).where(User.id == ctx.owner_id))
    username = user.scalar_one_or_none() or ""

    events = MOCK_CALENDARS.get(username, [])

    # Filter by time range
    range_order = {"today": 0, "tomorrow": 1, "this_week": 2, "next_week": 3}
    target = range_order.get(time_range, 2)
    filtered = [e for e in events if range_order.get(e["day"], 2) <= target]

    if not filtered:
        return json.dumps({
            "success": True,
            "events": [],
            "message": f"No events found for {time_range}.",
        })

    ctx.actions.append({"type": "calendar_checked", "time_range": time_range, "event_count": len(filtered)})

    return json.dumps({
        "success": True,
        "time_range": time_range,
        "events": filtered,
        "event_count": len(filtered),
        "message": f"Found {len(filtered)} event(s) for {time_range}.",
    })


async def handle_draft_email(ctx: ToolContext, params: dict) -> str:
    """Draft an email and save it as a capsule."""
    from src.crypto import content_hash, encrypt_text
    from src.embeddings import upsert_capsule_embedding

    to = params["to"]
    subject = params["subject"]
    body = params["body"]

    # Save as a capsule (draft)
    email_content = f"To: {to}\nSubject: {subject}\n\n{body}"
    capsule = KnowledgeCapsule(
        owner_id=ctx.owner_id,
        capsule_type="memory",
        title=f"Email Draft: {subject}",
        content_encrypted=encrypt_text(email_content, ctx.vault_key),
        content_hash=content_hash(email_content),
        visibility="private",
        category="work",
        freshness="temporary",
    )
    ctx.db.add(capsule)
    await ctx.db.flush()

    upsert_capsule_embedding(
        capsule.id,
        f"Email Draft: {subject} to {to}: {body[:200]}",
        {"capsule_id": capsule.id, "owner_id": ctx.owner_id, "visibility": "private"},
    )

    # Create notification
    notification = Notification(
        user_id=ctx.owner_id,
        notification_type="email_draft",
        title=f"Email draft saved: {subject}",
        body=f"To: {to}. Draft saved to your vault.",
        related_id=capsule.id,
    )
    ctx.db.add(notification)
    await ctx.db.flush()

    ctx.actions.append({
        "type": "email_drafted",
        "to": to,
        "subject": subject,
        "capsule_id": capsule.id,
    })

    return json.dumps({
        "success": True,
        "capsule_id": capsule.id,
        "to": to,
        "subject": subject,
        "message": f"Email draft to {to} saved to your vault. Subject: '{subject}'.",
    })


async def execute_tool(tool_name: str, tool_input: dict, ctx: ToolContext) -> str:
    """Route a tool call to its handler. Returns JSON string."""
    if tool_name == "search_vault":
        return await handle_search_vault(ctx, tool_input["query"])
    elif tool_name == "save_capsule":
        return await handle_save_capsule(ctx, tool_input)
    elif tool_name == "web_search":
        return await handle_web_search(ctx, tool_input["query"], tool_input.get("context", ""))
    elif tool_name == "create_task":
        return await handle_create_task(ctx, tool_input)
    elif tool_name == "discover_agents":
        return await handle_discover_agents(ctx, tool_input)
    elif tool_name == "query_peer":
        return await handle_query_peer(ctx, tool_input)
    elif tool_name == "request_quotes":
        return await handle_request_quotes(ctx, tool_input)
    elif tool_name == "list_connections":
        return await handle_list_connections(ctx)
    elif tool_name == "list_services":
        return await handle_list_services(ctx)
    elif tool_name == "discover_networks":
        return await handle_discover_networks(ctx, tool_input.get("interest", ""))
    elif tool_name == "check_calendar":
        return await handle_check_calendar(ctx, tool_input.get("time_range", "this_week"))
    elif tool_name == "draft_email":
        return await handle_draft_email(ctx, tool_input)
    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})


# ═══════════════════════════════════════════════════════════════
# System Prompts
# ═══════════════════════════════════════════════════════════════

def build_trust_context(trust_level: str, shared_networks: list[Network], requester_name: str, owner_name: str = "") -> str:
    """Build human-readable trust context for the agent prompt."""
    if trust_level == "private":
        return f"{requester_name} is the vault owner. Full access to all knowledge."
    elif trust_level == "network":
        network_names = ", ".join(n.name for n in shared_networks)
        return (
            f"{requester_name} is connected and shares these networks: {network_names}. "
            f"They can access open capsules, internal capsules shared to these networks, "
            f"and any capsules explicitly shared with them."
        )
    elif trust_level == "connected":
        return (
            f"{requester_name} is directly connected to {owner_name or 'your owner'} but shares no pools/networks.\n\n"
            f"CONNECTED-TRUST RULES:\n"
            f"- You may acknowledge knowing {requester_name} and being connected\n"
            f"- Only share information from the open capsules listed below\n"
            f"- Do NOT reveal internal capsule content, network member names, or private information\n"
            f"- You may suggest they join a shared pool for deeper access\n"
            f"- If you don't have open information for their question, say: \"I don't have that information available at our current trust level. "
            f"You could ask {owner_name or 'my owner'} to invite you to a shared pool for more access.\""
        )
    else:
        return (
            f"{requester_name} has public access only. "
            f"They are NOT in any of your owner's networks and have NO trusted relationship.\n\n"
            f"STRICT PUBLIC-TRUST RULES:\n"
            f"- Only share information from the open capsules listed below\n"
            f"- NEVER mention, name, or hint at other people, contacts, family, team members, or network members\n"
            f"- NEVER suggest \"ask someone else\", \"reach out to\", or \"you might want to contact\"\n"
            f"- NEVER reference the existence of groups, teams, families, networks, or pools\n"
            f"- NEVER say \"I know someone who\", \"we have\", \"our team\", or similar\n"
            f"- If you don't have information in the open capsules, say ONLY: \"I don't have that information available.\"\n"
            f"- Do NOT explain WHY you can't share — just say you don't have it"
        )


def format_capsules(capsules: list[dict]) -> str:
    """Format capsules for the agent prompt.

    Superseded capsules are marked and sorted last. Non-superseded capsules
    are sorted by authority_weight (descending).
    """
    if not capsules:
        return "No knowledge capsules available for this requester."

    # Sort: non-superseded first, then by authority_weight descending
    sorted_capsules = sorted(
        capsules,
        key=lambda c: (c.get("is_superseded", False), -c.get("authority_weight", 1.0)),
    )

    parts = []
    for c in sorted_capsules:
        superseded_tag = "[SUPERSEDED by newer version] " if c.get("is_superseded") else ""

        freshness_note = ""
        if c.get("expires_at"):
            freshness_note = f" [Expires: {c['expires_at']}]"
        elif c.get("freshness") == "temporary":
            freshness_note = " [Temporary — may be outdated]"

        gov_flags = []
        if c.get("emergency_accessible"):
            gov_flags.append("emergency-accessible")
        if c.get("can_reshare"):
            gov_flags.append("reshare-ok")
        gov_str = f" | Flags: {', '.join(gov_flags)}" if gov_flags else ""

        parts.append(
            f"{superseded_tag}[{c['capsule_type'].upper()}] {c['title']}{freshness_note}\n"
            f"Visibility: {c.get('visibility', c.get('tier', 'private'))} | Category: {c.get('category', 'general')}{gov_str}\n"
            f"{c['content']}\n"
        )
    return "\n---\n".join(parts)


def format_networks(networks: list[dict]) -> str:
    """Format the owner's networks for the self-query prompt."""
    if not networks:
        return "You don't belong to any networks yet."
    parts = []
    for n in networks:
        parts.append(f"- {n['name']} ({n['network_type']})")
    return "\n".join(parts)


# ── Cross-query prompt (read-only, no tools) ──

CROSS_QUERY_SYSTEM_PROMPT = """You are {owner_name}'s personal AI agent in the TrustMesh network.

You hold {owner_name}'s knowledge and share it appropriately based on who's asking.

## Who Is Asking
Requester: {requester_name}
Trust level: {trust_level}
{trust_context}

## Your Knowledge
These are the knowledge capsules you can draw from for this requester:

{formatted_capsules}

## Sharing Rules
1. ONLY use information from the capsules above — never fabricate
2. Match the capsule type to how you present information:
   - Memories: share naturally, conversationally
   - Skills: explain with the detail level appropriate for the question
   - Procedures: be precise and complete — these may involve health/safety
   - Schedules: include specific times, dates, and details
   - Preferences: state clearly, especially allergies or medical info
   - Contacts: share contact details when relevant to the question
3. If the question asks about something not in your capsules, say you don't have that information
4. NEVER reveal information beyond what the capsules above contain
5. For health/medical procedures, always err on the side of completeness and accuracy
6. Be warm and helpful — you represent {owner_name}
7. Keep responses concise but complete. Don't add unnecessary preamble.
8. **Reshare control**: If a capsule has can_reshare=false (or the flag isn't set), tell the requester: "This information is shared for your reference only — please don't pass it along."
9. **Visibility awareness**: Only share capsules that appear in the list above. The system has already filtered by the requester's access level.

## Information Boundary Rules (CRITICAL)
- NEVER mention names of people who are NOT the requester or the owner — even if they appear in capsule content
- NEVER suggest the requester "ask someone else" or "reach out to" another person
- NEVER reveal the existence or names of networks, groups, teams, pools, or families
- NEVER hint that more information exists beyond what you're sharing ("I have more but can't share" is a leak)
- If you lack information, say "I don't have that information" — NOT "someone else might know"
- These rules protect the privacy of everyone in the trust network"""


# ── Self-query prompt (tool-enabled) ──

SELF_QUERY_SYSTEM_PROMPT = """You are {owner_name}'s personal AI agent in the TrustMesh network.

You are talking directly to {owner_name} (your owner). You have FULL access to their vault and can also SAVE new knowledge.

## Your Networks
{networks_list}

## Your Current Knowledge
{formatted_capsules}

## What You Can Do
You have eleven tools:

1. **search_vault** — Search for existing capsules before saving. ALWAYS search first to avoid duplicates.
2. **save_capsule** — Save new knowledge or update existing capsules.
3. **web_search** — Search the web for real information (services, prices, reviews, current events).
4. **create_task** — Track multi-step work for your owner (appears in their dashboard).
5. **query_peer** — Ask another person's or service's agent a question (trust rules apply).
6. **request_quotes** — Get quotes from service providers in the mesh.
7. **list_connections** — See who you're connected to and shared networks. Use before query_peer.
8. **list_services** — See what service providers are in the mesh. Use before request_quotes.
9. **discover_networks** — Find public networks/groups the owner can join (music, dance, sports, neighborhood, etc.).
10. **check_calendar** — Check the owner's calendar for upcoming events, meetings, and appointments.
11. **draft_email** — Compose and save an email draft (saved to vault as a capsule).

## When to use tools — be PROACTIVE:
- User asks about services, businesses, or providers → ALWAYS list_services first, then request_quotes for matching ones, then web_search for more
- User asks "do you know any X?" where X is a type of business/provider (hospitals, clinics, tutors, cleaners, etc.) → list_services FIRST, then web_search
- User asks about healthcare, hospitals, doctors, medical help → list_services first (TrustMesh has healthcare providers!), then web_search
- User asks "what do I need to prepare?" → search_vault + list_connections, then query_peer relevant family members
- User says "remember X" → search_vault (check dups) then save_capsule
- User asks complex question → create_task to track, then research with multiple tools
- User mentions a specific person → list_connections to check access, then query_peer
- User asks about current events or external data → web_search
- User asks "who can help?" or "find me a..." → list_services + request_quotes + web_search (all three!)
- User asks about family plans → search_vault + query_peer family members for their info
- User asks about groups, communities, social clubs → discover_networks (with interest filter if specific)
- User asks "what can I join?" or "any groups nearby?" → discover_networks
- User asks about schedule, calendar, meetings, appointments → check_calendar
- User asks "what's on my calendar?" or "when is my next meeting?" → check_calendar
- User asks to write/draft/compose an email → draft_email
- User asks about upcoming plans → check_calendar + search_vault

## IMPORTANT: Always check the mesh FIRST
When the user asks about ANY type of provider, service, or business — ALWAYS call list_services before web_search.
TrustMesh has registered service providers (hospitals, tutors, cleaners, handyman, ambulance) and their agents can be queried directly.
The mesh is always more trustworthy than web results.

## Be Proactive
When you can anticipate what the user needs, DO IT:
- If they ask about a visit, also check schedules, related contacts, and query family agents
- If they ask about a service, compare mesh providers AND web results
- If they ask to remember something, also check if it affects schedules or other capsules
- Always try to give a COMPLETE answer, not just a partial one

## Smart Memory Rules

### Before Saving: ALWAYS Search First
When the owner asks you to save/remember/note something:
1. First call `search_vault` with relevant keywords to find existing capsules
2. If a closely related capsule exists, UPDATE it (pass `existing_capsule_id`) rather than creating a duplicate
3. If no match, create a new capsule

### Classification Intelligence
Classify saved knowledge smartly and ACCURATELY. Pay close attention to what the user actually said:

**capsule_type:**
- "preference" — likes, dislikes, allergies, dietary restrictions, favorites
- "memory" — events, observations, things that happened
- "skill" — expertise, how-to knowledge
- "procedure" — step-by-step routines, care instructions
- "schedule" — appointments, trips, deadlines
- "contact" — people, phone numbers, emails

**CRITICAL — Distinguish Dislikes from Allergies:**
- "I hate X" / "I don't like X" / "I can't stand X" → This is a DISLIKE/preference, NOT a medical condition. Title should reflect this (e.g., "Jane's Food Dislikes", NOT "Jane's Peanut Allergy").
- "I'm allergic to X" / "X allergy" / "allergic reaction" → This IS an allergy. Category should be "health".
- Do NOT escalate dislikes into medical conditions. If someone says "I hate peanuts", that means they don't enjoy eating them — it does NOT mean they have a peanut allergy. These are fundamentally different.

**visibility (4-level data governance):**
- `private` — Owner only. Diary entries, personal secrets, sensitive notes.
- `internal` — Owner + trusted networks. Health/safety info shared with family, work data shared with team.
- `shareable` — Explicitly shared with specific people. Temporal — access grants expire.
- `open` — Discoverable by anyone. Professional bio, public skills.

**Category defaults (use these unless owner says otherwise):**
| Category | Default visibility | emergency_accessible | can_reshare |
|----------|-------------------|---------------------|-------------|
| health   | internal          | true                | false       |
| personal | private           | false               | false       |
| work     | internal          | false               | false       |
| family   | internal          | false               | false       |
| home     | internal          | false               | false       |
| general  | open              | false               | true        |

After saving, confirm the governance: "I saved Rose's medication list as **internal** with emergency access enabled. Your Care Circle can see it, and verified healthcare providers can access it in emergencies."

**emergency_accessible:** Set `true` for health capsules (allergies, medications, conditions). Verified healthcare providers can access these via UCAN tokens regardless of visibility level.

**can_reshare:** Set `true` for open/general capsules. When `false`, viewing agents say "This is shared for your reference only."

**category:**
- Actual medical allergies, medications → "health"
- Food dislikes, favorite foods → "personal" (NOT "health" unless it's a real allergy)
- House repairs → "home", coworker info → "work", hobbies → "personal"

**freshness:** Facts/allergies → "permanent". Events/locations → "temporary". Routines → "recurring"
**title:** Include the person's name if about someone else. Be descriptive but concise. Reflect what was actually said — don't exaggerate or medicalize.

### Merging & Dedup
- If the owner says "Peter is allergic to shellfish" and you find an existing "Peter's Medical Info" capsule, UPDATE it to include the shellfish allergy alongside existing info
- If you find a capsule about the same topic but a different person, create a NEW capsule (not a duplicate)
- When updating, merge the new information with the old content — don't lose existing data

### Network Assignment
- Family health/safety info → share with family network (visibility: internal)
- Work-related knowledge → share with work network (visibility: internal)
- Personal observations about relationships → keep "private" unless owner specifies
- If unsure, default to "private" and tell the owner they can share it later

## Response Style
- Be conversational and warm — you're talking to your owner
- After saving, confirm what you saved and how you classified it
- If you found a duplicate and merged, explain that
- You can also answer questions about the owner's knowledge (read from capsules)
- Keep responses concise. Don't over-explain unless asked."""


# ═══════════════════════════════════════════════════════════════
# Sensitivity Detection (for TEE routing)
# ═══════════════════════════════════════════════════════════════

SENSITIVE_CATEGORIES = {"medical", "financial", "legal", "insurance"}
SENSITIVE_KEYWORDS = {
    "medical", "health", "diagnosis", "prescription", "medication",
    "blood pressure", "dialysis", "surgery", "therapy", "treatment",
    "financial", "bank", "account number", "ssn", "social security",
    "credit card", "tax", "salary", "income", "investment",
    "insurance", "policy number", "claim",
}


def detect_sensitivity(capsules: list[dict], question: str = "") -> str:
    """Detect if a query involves sensitive data.

    Returns "sensitive" if medical/financial/legal capsules are involved
    or the question mentions sensitive topics. Otherwise "standard".
    """
    # Check capsule categories
    for c in capsules:
        cat = (c.get("category") or "").lower()
        ctype = (c.get("capsule_type") or c.get("type") or "").lower()
        if cat in SENSITIVE_CATEGORIES or ctype in SENSITIVE_CATEGORIES:
            return "sensitive"

    # Check question keywords
    q_lower = question.lower()
    if any(kw in q_lower for kw in SENSITIVE_KEYWORDS):
        return "sensitive"

    return "standard"


# ═══════════════════════════════════════════════════════════════
# Agent Response Functions
# ═══════════════════════════════════════════════════════════════

def _minimize_capsules_for_public(capsules: list[dict]) -> list[dict]:
    """Strip potentially leaky metadata from capsules at public trust.

    Removes fields that could help an attacker map the network topology
    (e.g., 'source', 'shared_by', 'related_users') while keeping the
    core content that the capsule owner chose to make public.
    """
    stripped = []
    for c in capsules:
        clean = {
            "capsule_type": c.get("capsule_type", "note"),
            "title": c.get("title", ""),
            "content": c.get("content", ""),
            "visibility": c.get("visibility", "open"),
            "category": c.get("category", "general"),
        }
        # Keep governance flags — they're about the capsule, not the network
        if c.get("emergency_accessible"):
            clean["emergency_accessible"] = True
        stripped.append(clean)
    return stripped


async def agent_respond(
    agent: Agent,
    question: str,
    trust_level: str,
    shared_networks: list[Network],
    capsules: list[dict],
    requester_name: str,
    owner_name: str,
) -> str:
    """Cross-query: agent reasons about what to share (read-only, no tools)."""
    trust_context = build_trust_context(trust_level, shared_networks, requester_name, owner_name)

    # Context minimization: strip metadata at public trust to reduce leak surface
    if trust_level == "public":
        capsules = _minimize_capsules_for_public(capsules)

    formatted = format_capsules(capsules)

    system_prompt = CROSS_QUERY_SYSTEM_PROMPT.format(
        owner_name=owner_name,
        requester_name=requester_name,
        trust_level=trust_level,
        trust_context=trust_context,
        formatted_capsules=formatted,
    )

    sensitivity = detect_sensitivity(capsules, question)
    router = get_router()
    response = await router.complete(
        messages=[{"role": "user", "content": question}],
        system=system_prompt,
        model="default",
        sensitivity=sensitivity,
        max_tokens=1024,
    )

    return response.text or ""


async def agent_respond_with_tools(
    agent: Agent,
    question: str,
    capsules: list[dict],
    owner_name: str,
    tool_context: ToolContext,
) -> tuple[str, list[dict]]:
    """Self-query: agent responds with tool access (search, save, update).

    Returns (response_text, actions_taken).
    """
    formatted = format_capsules(capsules)
    networks_list = format_networks(tool_context.networks)

    system_prompt = SELF_QUERY_SYSTEM_PROMPT.format(
        owner_name=owner_name,
        formatted_capsules=formatted,
        networks_list=networks_list,
    )

    sensitivity = detect_sensitivity(capsules, question)
    router = get_router()
    messages: list[dict] = [{"role": "user", "content": question}]

    # Tool-use loop (max 5 round-trips to prevent runaway)
    for _ in range(5):
        response = await router.complete(
            messages=messages,
            system=system_prompt,
            model="fast",
            sensitivity=sensitivity,
            tools=AGENT_TOOLS,
            max_tokens=2048,
        )

        # If the response is a final text (no tool use), we're done
        if response.stop_reason == "end_turn":
            return response.text or "Done.", tool_context.actions

        # Process tool calls
        if response.stop_reason == "tool_use":
            # Build assistant content blocks for Anthropic message format
            assistant_content = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool call, scan results with Citadel, collect
            tool_results = []
            for tc in response.tool_calls:
                result_str = await execute_tool(tc.name, tc.input, tool_context)
                # Citadel scan on tool outputs (web_search, query_peer most important)
                if tc.name in ("web_search", "query_peer", "request_quotes"):
                    from src import citadel
                    output_scan = await citadel.scan_output(result_str)
                    if not output_scan.is_safe:
                        log.warning(f"Citadel flagged {tc.name} output: {output_scan.findings}")
                        result_str = json.dumps({
                            "warning": "Content flagged by security scan",
                            "findings": output_scan.findings,
                            "original_truncated": result_str[:200] + "...",
                        })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result_str,
                })

            # Send tool results back to the model
            messages.append({"role": "user", "content": tool_results})
        else:
            return (
                response.text or "I'm not sure how to help with that.",
                tool_context.actions,
            )

    # Max iterations reached
    return "I've completed the requested actions.", tool_context.actions


# ═══════════════════════════════════════════════════════════════
# Streaming Agent Responses
# ═══════════════════════════════════════════════════════════════

async def agent_respond_streaming(
    agent: Agent,
    question: str,
    trust_level: str,
    shared_networks: list[Network],
    capsules: list[dict],
    requester_name: str,
    owner_name: str,
    conversation_history: list[dict] | None = None,
):
    """Cross-query streaming: yields text chunks as they arrive."""
    trust_context = build_trust_context(trust_level, shared_networks, requester_name, owner_name)
    formatted = format_capsules(capsules)

    system_prompt = CROSS_QUERY_SYSTEM_PROMPT.format(
        owner_name=owner_name,
        requester_name=requester_name,
        trust_level=trust_level,
        trust_context=trust_context,
        formatted_capsules=formatted,
    )

    # Build messages with conversation history for continuity
    messages: list[dict] = []
    if conversation_history:
        for msg in conversation_history[-10:]:  # Last 10 exchanges max
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    sensitivity = detect_sensitivity(capsules, question)
    router = get_router()
    async for chunk in router.stream_complete(
        messages=messages,
        system=system_prompt,
        model="default",
        sensitivity=sensitivity,
        max_tokens=1024,
    ):
        yield chunk


async def agent_respond_with_tools_streaming(
    agent: Agent,
    question: str,
    capsules: list[dict],
    owner_name: str,
    tool_context: ToolContext,
    conversation_history: list[dict] | None = None,
):
    """Self-query streaming: runs tool loop non-streaming, then streams final response.

    Yields tuples of (event_type, data):
      ("tool", {"name": ..., "input": ...})  — tool being called
      ("text", "chunk")                       — text being streamed
      ("actions", [...])                      — final actions list
    """
    formatted = format_capsules(capsules)
    networks_list = format_networks(tool_context.networks)

    system_prompt = SELF_QUERY_SYSTEM_PROMPT.format(
        owner_name=owner_name,
        formatted_capsules=formatted,
        networks_list=networks_list,
    )

    sensitivity = detect_sensitivity(capsules, question)
    router = get_router()

    # Build messages with conversation history for continuity
    messages: list[dict] = []
    if conversation_history:
        for msg in conversation_history[-10:]:  # Last 10 exchanges max
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    # Tool-use loop (non-streaming for tool rounds)
    for _ in range(5):
        response = await router.complete(
            messages=messages,
            system=system_prompt,
            model="fast",
            sensitivity=sensitivity,
            tools=AGENT_TOOLS,
            max_tokens=2048,
        )

        if response.stop_reason == "end_turn":
            # Final response — yield the text we already have
            text = response.text or "Done."
            # Yield in chunks for streaming feel
            chunk_size = 4
            words = text.split(" ")
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                if i > 0:
                    chunk = " " + chunk
                yield ("text", chunk)
            yield ("actions", tool_context.actions)
            return

        if response.stop_reason == "tool_use":
            assistant_content = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for tc in response.tool_calls:
                yield ("tool", {"name": tc.name, "input": tc.input})
                result_str = await execute_tool(tc.name, tc.input, tool_context)
                if tc.name in ("web_search", "query_peer", "request_quotes"):
                    from src import citadel
                    output_scan = await citadel.scan_output(result_str)
                    if not output_scan.is_safe:
                        result_str = json.dumps({
                            "warning": "Content flagged by security scan",
                            "findings": output_scan.findings,
                            "original_truncated": result_str[:200] + "...",
                        })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result_str,
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            # Unexpected stop — just yield the text
            if response.text:
                yield ("text", response.text)
            yield ("actions", tool_context.actions)
            return

    yield ("text", "I've completed the requested actions.")
    yield ("actions", tool_context.actions)


# ═══════════════════════════════════════════════════════════════
# Profile Extraction (Haiku 4.5 — fast, structured output)
# ═══════════════════════════════════════════════════════════════

PROFILE_EXTRACTION_PROMPT = """Extract structured profile data from this user bio. Return valid JSON only.

Bio: "{bio}"
Display name: "{display_name}"

Return this exact JSON structure (use null for unknown fields, empty arrays for no data):
{{
  "occupation": {{"title": "string or null", "industry": "string or null"}},
  "skills": [{{"name": "string", "category": "technical|professional|personal|certified"}}],
  "interests": [{{"name": "string", "category": "hobby|sport|academic|creative"}}],
  "family_status": "single|married|parent|unknown",
  "age_range": "string or null",
  "location_hints": ["strings"]
}}

Be concise. Only extract what's clearly stated or strongly implied."""


async def extract_profile(bio: str, display_name: str) -> dict | None:
    """Extract structured profile data from a bio using fast model."""
    if not bio or not bio.strip():
        return None
    try:
        router = get_router()
        response = await router.complete(
            messages=[{
                "role": "user",
                "content": PROFILE_EXTRACTION_PROMPT.format(bio=bio, display_name=display_name),
            }],
            model="fast",
            max_tokens=500,
        )
        text = (response.text or "").strip()
        # Extract JSON from response (handle markdown code blocks)
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        log.warning(f"Profile extraction failed for {display_name}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# Morning Briefing
# ═══════════════════════════════════════════════════════════════

INTAKE_SYSTEM_PROMPT = """You are the onboarding agent for TrustMesh, helping {owner_name} set up their personal AI agent.

Your goal: learn about this person through a warm, natural conversation and save their key information as knowledge capsules in their encrypted vault.

## Conversation Context
{conversation_history}

## What to gather (in order of priority):
1. **About them** — What they do (job, school), their skills, interests, hobbies
2. **Family/household** — Who they live with, family members, pets
3. **Important contacts** — Close friends, family members, colleagues they'd want their agent to know about
4. **Preferences** — Dietary restrictions, allergies, likes/dislikes
5. **Schedule/routine** — Regular commitments, upcoming events
6. **What they want from TrustMesh** — What kind of info they want to share, who they want to connect with

## Rules:
- Ask ONE question at a time. Keep it conversational, not interrogation-like.
- After each answer, IMMEDIATELY save the information using save_capsule.
- Classify accurately: use the right capsule_type, tier, category.
- Default to "private" tier unless they mention wanting to share something.
- Be warm, encouraging. Celebrate what you learn ("That's great! Your agent will remember that.")
- After 4-6 exchanges, wrap up naturally. Don't drag it out.
- If they say "skip" or "done" or "that's it", wrap up immediately.
- In your final message, summarize what you saved and suggest they explore the dashboard.

## Capsule types to use:
- "skill" for their job, expertise, domain knowledge
- "preference" for likes, dislikes, dietary info, allergies
- "contact" for family members, friends, colleagues
- "schedule" for regular commitments, upcoming events
- "memory" for personal stories, observations
- "procedure" for routines, how they do things

Always search_vault before saving to avoid duplicates (vault may be empty for new users, that's fine)."""

INTAKE_TOOLS = [
    AGENT_TOOLS[0],  # search_vault
    AGENT_TOOLS[1],  # save_capsule
]


async def run_intake_step(
    owner_name: str,
    user_message: str,
    conversation_history: list[dict],
    tool_context: ToolContext,
) -> tuple[str, list[dict]]:
    """Run one step of the intake conversation. Returns (response_text, actions)."""
    # Format conversation history for the system prompt
    history_text = ""
    for msg in conversation_history:
        role = "You" if msg["role"] == "assistant" else owner_name
        history_text += f"{role}: {msg['content']}\n"

    system_prompt = INTAKE_SYSTEM_PROMPT.format(
        owner_name=owner_name,
        conversation_history=history_text or "(This is the start of the conversation)",
    )

    router = get_router()
    messages: list[dict] = [{"role": "user", "content": user_message}]

    # Tool-use loop (max 3 round-trips for intake)
    for _ in range(3):
        response = await router.complete(
            messages=messages,
            system=system_prompt,
            model="fast",
            tools=INTAKE_TOOLS,
            max_tokens=1024,
        )

        if response.stop_reason == "end_turn":
            return response.text or "Done.", tool_context.actions

        if response.stop_reason == "tool_use":
            assistant_content = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for tc in response.tool_calls:
                result_str = await execute_tool(tc.name, tc.input, tool_context)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result_str,
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            return response.text or "Let's continue.", tool_context.actions

    return "I've saved what we've discussed so far.", tool_context.actions


BRIEFING_SYSTEM_PROMPT = """You are {owner_name}'s personal agent. Create a concise {time_of_day} briefing.

Current time context: {time_of_day} on a {day_type}.
{day_guidance}

Prioritize: health/safety, time-sensitive items, then social.
Be warm but concise. Include specific times, dates, names.
Use markdown formatting with headers (NOT tables — use lists instead). Keep it under 500 words.
If there's little to report, keep it brief — no filler."""


def _get_briefing_time_context() -> tuple[str, str, str]:
    """Return (time_of_day, day_type, day_guidance) based on current local time."""
    from datetime import datetime
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()  # 0=Mon, 6=Sun

    if hour < 12:
        time_of_day = "morning"
    elif hour < 17:
        time_of_day = "afternoon"
    else:
        time_of_day = "evening"

    is_weekend = weekday >= 5
    day_type = "weekend" if is_weekend else "weekday"

    if is_weekend:
        day_guidance = (
            "It's the weekend — focus on personal plans, family activities, rest, and any fun events. "
            "De-emphasize work tasks unless they're truly urgent deadlines."
        )
    elif time_of_day == "morning":
        day_guidance = (
            "Group by: Today's Schedule, Action Items, Upcoming, Network Updates. "
            "Focus on what needs attention today."
        )
    elif time_of_day == "afternoon":
        day_guidance = (
            "Group by: Remaining Today, Evening Plans, Tomorrow Preview, Updates. "
            "Focus on what's left today and what's coming up."
        )
    else:
        day_guidance = (
            "Group by: Tonight, Tomorrow Preview, This Week Ahead, Updates. "
            "Help wind down — summarize what happened and what's next."
        )

    return time_of_day, day_type, day_guidance


async def generate_briefing(
    owner_name: str,
    capsules: list[dict],
    pending_tasks: list[dict],
    recent_network_capsules: list[dict],
    pending_requests: int,
    unread_notifications: int,
) -> str:
    """Generate a time-aware briefing using Opus 4.6."""
    time_of_day, day_type, day_guidance = _get_briefing_time_context()

    context_parts = []

    if capsules:
        context_parts.append("## Your Knowledge (schedules, tasks, events):")
        for c in capsules[:10]:
            context_parts.append(f"- [{c['capsule_type']}] {c['title']}: {c['content'][:200]}")

    if pending_tasks:
        context_parts.append("\n## Pending Tasks:")
        for t in pending_tasks:
            context_parts.append(f"- [{t['status']}] {t['title']}: {t['description'][:100]}")

    if recent_network_capsules:
        context_parts.append("\n## Recent Network Updates:")
        for c in recent_network_capsules[:5]:
            context_parts.append(f"- [{c.get('owner_name', 'Someone')}] {c['title']}: {c['content'][:150]}")

    if pending_requests:
        context_parts.append(f"\n## Pending: {pending_requests} connection request(s)")

    if unread_notifications:
        context_parts.append(f"\n## Unread: {unread_notifications} notification(s)")

    greeting = {"morning": "Good morning", "afternoon": "Good afternoon", "evening": "Good evening"}[time_of_day]

    if not context_parts:
        return f"{greeting}, {owner_name}! Your schedule is clear and there are no pending items. Enjoy your {'weekend' if day_type == 'weekend' else 'day'}!"

    context = "\n".join(context_parts)

    router = get_router()
    response = await router.complete(
        messages=[{"role": "user", "content": f"Here's what I know. Generate my briefing:\n\n{context}"}],
        system=BRIEFING_SYSTEM_PROMPT.format(
            owner_name=owner_name,
            time_of_day=time_of_day,
            day_type=day_type,
            day_guidance=day_guidance,
        ),
        model="default",
        max_tokens=1024,
    )

    return response.text or f"{greeting}, {owner_name}!"
