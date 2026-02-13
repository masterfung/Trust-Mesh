"""Trust-tiered gossip protocol — the core query engine."""

import json
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import citadel, embeddings
from src.agents import ToolContext, agent_respond, agent_respond_with_tools
from src.crypto import decrypt_text
from src.rate_limit import check_query_rate, record_query
from src.audit import log_event
from src.models import (
    Agent,
    CapsuleNetworkAccess,
    KnowledgeCapsule,
    Network,
    NetworkMembership,
    Notification,
    Query,
    User,
)
from src.trust import resolve_trust_level


async def get_accessible_capsule_ids(
    db: AsyncSession,
    owner_id: str,
    trust_level: str,
    shared_networks: list[Network],
) -> list[str]:
    """Get IDs of capsules accessible at the given trust level."""
    if trust_level == "private":
        result = await db.execute(
            select(KnowledgeCapsule.id).where(
                KnowledgeCapsule.owner_id == owner_id,
                KnowledgeCapsule.is_archived == False,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    # Public capsules always accessible
    public_result = await db.execute(
        select(KnowledgeCapsule.id).where(
            KnowledgeCapsule.owner_id == owner_id,
            KnowledgeCapsule.tier == "public",
            KnowledgeCapsule.is_archived == False,  # noqa: E712
        )
    )
    ids = list(public_result.scalars().all())

    if trust_level == "network" and shared_networks:
        network_ids = [n.id for n in shared_networks]
        network_result = await db.execute(
            select(CapsuleNetworkAccess.capsule_id)
            .join(KnowledgeCapsule, KnowledgeCapsule.id == CapsuleNetworkAccess.capsule_id)
            .where(
                CapsuleNetworkAccess.network_id.in_(network_ids),
                KnowledgeCapsule.owner_id == owner_id,
                KnowledgeCapsule.is_archived == False,  # noqa: E712
            )
        )
        ids.extend(network_result.scalars().all())

    return list(set(ids))


async def load_capsules_decrypted(
    db: AsyncSession, capsule_ids: list[str], vault_key: bytes
) -> list[dict]:
    """Load and decrypt capsules by ID."""
    if not capsule_ids:
        return []
    result = await db.execute(
        select(KnowledgeCapsule).where(KnowledgeCapsule.id.in_(capsule_ids))
    )
    capsules = result.scalars().all()
    decrypted = []
    for c in capsules:
        try:
            content = decrypt_text(c.content_encrypted, vault_key)
        except Exception:
            content = "Content is securely encrypted. Owner's vault key is required to view."
        decrypted.append({
            "id": c.id,
            "capsule_type": c.capsule_type,
            "title": c.title,
            "content": content,
            "tier": c.tier,
            "category": c.category,
            "freshness": c.freshness,
            "expires_at": str(c.expires_at) if c.expires_at else None,
        })
    return decrypted


async def get_user_networks(db: AsyncSession, user_id: str) -> list[dict]:
    """Get all networks a user belongs to, as dicts for tool context."""
    result = await db.execute(
        select(Network)
        .join(NetworkMembership, NetworkMembership.network_id == Network.id)
        .where(NetworkMembership.user_id == user_id)
    )
    networks = result.scalars().all()
    return [
        {"id": n.id, "name": n.name, "network_type": n.network_type}
        for n in networks
    ]


def _error_result(
    from_user_id: str,
    to_user_id: str,
    question: str,
    response: str,
    *,
    trust_level: str = "public",
    shared_networks: list[str] | None = None,
    latency_ms: int = 0,
) -> dict:
    """Build a consistent denied-query result dict. DRY helper for all error paths."""
    return {
        "id": f"err-{int(time.time() * 1000)}",
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "question": question,
        "trust_level": trust_level,
        "shared_networks": shared_networks or [],
        "response": response,
        "decision": "denied",
        "citadel_input": None,
        "citadel_output": None,
        "latency_ms": latency_ms,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def query_agent(
    db: AsyncSession,
    from_user_id: str,
    to_user_id: str,
    question: str,
    vault_keys: dict[str, bytes],
    query_depth: int = 0,
) -> dict:
    """The core inter-agent query flow.

    Two modes:
    - Self-query (from == to): Agent has tools (search, save, update)
    - Cross-query (from != to): Agent is read-only (trust-based sharing)

    Flow:
    1. Resolve trust level
    2. Citadel: scan input
    3. Get accessible capsules
    4. Semantic retrieval
    5. Opus 4.6 agent responds (with or without tools)
    6. Citadel: scan output
    7. Log and return
    """
    start = time.time()
    is_self_query = from_user_id == to_user_id

    # Load users and agent
    from_user = await db.get(User, from_user_id)
    to_user = await db.get(User, to_user_id)
    if not from_user or not to_user:
        return _error_result(from_user_id, to_user_id, question, "User not found")

    agent_result = await db.execute(
        select(Agent).where(Agent.owner_id == to_user_id)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        return _error_result(from_user_id, to_user_id, question, "Agent not found")

    # 1. Resolve trust
    if is_self_query:
        trust_level = "private"
        shared_networks = []
        network_names = []
    else:
        trust_level, shared_networks = await resolve_trust_level(db, from_user_id, to_user_id)
        network_names = [n.name for n in shared_networks]

    # 1b. Rate limit check (skip for self-query)
    if not is_self_query:
        rate_ok, rate_reason = check_query_rate(from_user_id, to_user_id, trust_level)
        if not rate_ok:
            return _error_result(
                from_user_id, to_user_id, question, rate_reason,
                trust_level=trust_level, shared_networks=network_names,
            )

    # 2. Citadel: scan input (skip for self-query — you can't inject yourself)
    input_scan = None
    if not is_self_query:
        input_scan = await citadel.scan_input(question)
        if input_scan.decision == "BLOCK":
            latency = int((time.time() - start) * 1000)
            query_record = Query(
                from_user_id=from_user_id,
                to_user_id=to_user_id,
                question=question,
                trust_level=trust_level,
                shared_networks=json.dumps(network_names),
                decision="denied",
                response="Blocked: potential security threat detected",
                citadel_input_score=input_scan.heuristic_score,
                citadel_input_decision=input_scan.decision,
                latency_ms=latency,
            )
            db.add(query_record)
            await db.commit()
            return {
                "id": query_record.id,
                "from_user_id": from_user_id,
                "to_user_id": to_user_id,
                "question": question,
                "decision": "denied",
                "response": "Blocked: potential security threat detected",
                "trust_level": trust_level,
                "shared_networks": network_names,
                "citadel_input": {
                    "score": input_scan.heuristic_score,
                    "decision": input_scan.decision,
                },
                "latency_ms": latency,
                "created_at": query_record.created_at.isoformat(),
            }

    # 3. Get accessible capsules
    accessible_ids = await get_accessible_capsule_ids(db, to_user_id, trust_level, shared_networks)

    # 4. Semantic retrieval
    relevant_ids = embeddings.search_capsules(question, accessible_ids, top_k=5)
    if not relevant_ids:
        relevant_ids = accessible_ids[:5]  # Fallback: use first 5

    # 5. Load and decrypt capsules
    vault_key = vault_keys.get(to_user_id)
    if not vault_key:
        return _error_result(
            from_user_id, to_user_id, question,
            "Vault key not available — target user needs to log in first",
            trust_level=trust_level, shared_networks=network_names,
        )

    capsules = await load_capsules_decrypted(db, relevant_ids, vault_key)

    # 6. Opus 4.6 agent responds
    actions = []
    try:
        if is_self_query:
            # Self-query: tools enabled (search, save, update)
            user_networks = await get_user_networks(db, to_user_id)
            tool_context = ToolContext(
                db=db,
                vault_key=vault_key,
                owner_id=to_user_id,
                owner_name=to_user.display_name,
                networks=user_networks,
                query_depth=query_depth,
            )
            response_text, actions = await agent_respond_with_tools(
                agent=agent,
                question=question,
                capsules=capsules,
                owner_name=to_user.display_name,
                tool_context=tool_context,
            )
        else:
            # Cross-query: read-only
            response_text = await agent_respond(
                agent=agent,
                question=question,
                trust_level=trust_level,
                shared_networks=shared_networks,
                capsules=capsules,
                requester_name=from_user.display_name,
                owner_name=to_user.display_name,
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Agent error for user {to_user_id}: {e}")
        response_text = "I'm sorry, I encountered an issue processing your request. Please try again."

    # 7. Citadel: scan output (skip for self-query)
    output_scan = None
    decision = "allowed"
    if not is_self_query:
        output_scan = await citadel.scan_output(response_text)
        if not output_scan.is_safe:
            decision = "redacted"
            response_text = f"Response redacted: {', '.join(output_scan.findings)}"

    latency = int((time.time() - start) * 1000)

    # Record for rate limiting (skip self-query)
    if not is_self_query:
        record_query(from_user_id, to_user_id)

    # Log query
    query_record = Query(
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        question=question,
        trust_level=trust_level,
        shared_networks=json.dumps(network_names),
        response=response_text,
        decision=decision,
        citadel_input_score=input_scan.heuristic_score if input_scan else None,
        citadel_input_decision=input_scan.decision if input_scan else None,
        citadel_output_safe=output_scan.is_safe if output_scan else None,
        citadel_output_findings=json.dumps(output_scan.findings) if output_scan and output_scan.findings else None,
        latency_ms=latency,
    )
    db.add(query_record)
    await db.flush()

    # Create notification for cross-queries
    if not is_self_query:
        notification = Notification(
            user_id=to_user_id,
            notification_type="query_received",
            title=f"Query from {from_user.display_name}",
            body=question[:200],
            related_id=query_record.id,
        )
        db.add(notification)

    # Audit log for cross-queries
    if not is_self_query:
        await log_event(
            db,
            actor_user_id=from_user_id,
            target_user_id=to_user_id,
            action="cross_query",
            event_type="query",
            query_id=query_record.id,
            decision=decision,
            details={"trust_level": trust_level, "shared_networks": network_names},
        )

    await db.commit()
    await db.refresh(query_record)

    result = {
        "id": query_record.id,
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "question": question,
        "trust_level": trust_level,
        "shared_networks": network_names,
        "response": response_text,
        "decision": decision,
        "citadel_input": {
            "score": input_scan.heuristic_score if input_scan else None,
            "decision": input_scan.decision if input_scan else None,
        } if input_scan else None,
        "citadel_output": {
            "is_safe": output_scan.is_safe if output_scan else None,
            "findings": output_scan.findings if output_scan else None,
        } if output_scan else None,
        "latency_ms": latency,
        "created_at": query_record.created_at.isoformat(),
    }

    # Include agent actions for self-query
    if actions:
        result["agent_actions"] = actions

    return result
