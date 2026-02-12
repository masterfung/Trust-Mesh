"""Trust-tiered gossip protocol — the core query engine."""

import json
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import citadel, embeddings
from src.agents import agent_respond
from src.crypto import decrypt_text
from src.rate_limit import check_query_rate, record_query
from src.models import (
    Agent,
    CapsuleNetworkAccess,
    KnowledgeCapsule,
    Network,
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
            content = "[Decryption error]"
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


async def query_agent(
    db: AsyncSession,
    from_user_id: str,
    to_user_id: str,
    question: str,
    vault_keys: dict[str, bytes],
) -> dict:
    """The core inter-agent query flow.

    1. Resolve trust level
    2. Citadel: scan input
    3. Get accessible capsules
    4. Semantic retrieval
    5. Opus 4.6 agent responds
    6. Citadel: scan output
    7. Log and return
    """
    start = time.time()

    # Load users and agent
    from_user = await db.get(User, from_user_id)
    to_user = await db.get(User, to_user_id)
    if not from_user or not to_user:
        return {"decision": "denied", "response": "User not found", "latency_ms": 0}

    agent_result = await db.execute(
        select(Agent).where(Agent.owner_id == to_user_id)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        return {"decision": "denied", "response": "Agent not found", "latency_ms": 0}

    # 1. Resolve trust
    trust_level, shared_networks = await resolve_trust_level(db, from_user_id, to_user_id)
    network_names = [n.name for n in shared_networks]

    # 1b. Rate limit check (application-level, NOT Citadel)
    rate_ok, rate_reason = check_query_rate(from_user_id, to_user_id, trust_level)
    if not rate_ok:
        return {"decision": "denied", "response": rate_reason, "latency_ms": 0,
                "trust_level": trust_level, "shared_networks": network_names}

    # 2. Citadel: scan input
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
            "decision": "denied",
            "response": "Blocked: potential security threat detected",
            "trust_level": trust_level,
            "shared_networks": network_names,
            "citadel_input": {
                "score": input_scan.heuristic_score,
                "decision": input_scan.decision,
            },
            "latency_ms": latency,
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
        return {"decision": "denied", "response": "Vault key not available", "latency_ms": 0}

    capsules = await load_capsules_decrypted(db, relevant_ids, vault_key)

    # 6. Opus 4.6 agent responds
    try:
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
        response_text = f"Agent error: {e}"

    # 7. Citadel: scan output
    output_scan = await citadel.scan_output(response_text)
    decision = "allowed"
    if not output_scan.is_safe:
        decision = "redacted"
        response_text = f"Response redacted: {', '.join(output_scan.findings)}"

    latency = int((time.time() - start) * 1000)

    # Record for rate limiting
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
        citadel_input_score=input_scan.heuristic_score,
        citadel_input_decision=input_scan.decision,
        citadel_output_safe=output_scan.is_safe,
        citadel_output_findings=json.dumps(output_scan.findings) if output_scan.findings else None,
        latency_ms=latency,
    )
    db.add(query_record)
    await db.commit()
    await db.refresh(query_record)

    return {
        "id": query_record.id,
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "question": question,
        "trust_level": trust_level,
        "shared_networks": network_names,
        "response": response_text,
        "decision": decision,
        "citadel_input": {
            "score": input_scan.heuristic_score,
            "decision": input_scan.decision,
        },
        "citadel_output": {
            "is_safe": output_scan.is_safe,
            "findings": output_scan.findings,
        },
        "latency_ms": latency,
        "created_at": query_record.created_at.isoformat(),
    }
