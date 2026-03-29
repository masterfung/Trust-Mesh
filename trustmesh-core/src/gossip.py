"""Trust-tiered gossip protocol — the core query engine."""

import json
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import citadel, embeddings
from src.agents import ToolContext, agent_respond, agent_respond_with_tools
from src import transit_bridge
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
    requester_id: str | None = None,
    context_filter: str | None = None,
) -> list[str]:
    """Get IDs of capsules accessible at the given trust level.

    4-level visibility model:
    - private: owner only (self-query)
    - internal: owner + trusted networks (family, work team, care circle)
    - shareable: explicitly shared via allow-list grants (with expiry)
    - open: discoverable by anyone
    """
    from src.models import CapsuleShareGrant

    now = datetime.now(timezone.utc)
    base_filter = [
        KnowledgeCapsule.owner_id == owner_id,
        KnowledgeCapsule.is_archived == False,  # noqa: E712
        (KnowledgeCapsule.expires_at == None) | (KnowledgeCapsule.expires_at > now),  # noqa: E711
    ]
    if context_filter and context_filter != "all":
        base_filter.append(KnowledgeCapsule.context.in_([context_filter, "both"]))

    # Self-query: full access
    if trust_level == "private":
        result = await db.execute(
            select(KnowledgeCapsule.id).where(*base_filter)
        )
        return list(result.scalars().all())

    # Level 4: open capsules always accessible
    open_result = await db.execute(
        select(KnowledgeCapsule.id).where(
            *base_filter,
            KnowledgeCapsule.visibility == "open",
        )
    )
    ids = list(open_result.scalars().all())

    # Level 2: internal — accessible via shared networks
    if trust_level == "network" and shared_networks:
        network_ids = [n.id for n in shared_networks]

        # Category scoping: if ALL shared pools are category_scoped, restrict to allowed categories
        # If ANY pool is "standard", no category restriction (standard lifts all restrictions)
        allowed_categories = None
        has_standard = any(
            getattr(n, "pool_type", "standard") == "standard"
            for n in shared_networks
        )
        if not has_standard:
            cats = set()
            for n in shared_networks:
                raw = getattr(n, "shared_categories", None)
                if raw:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(parsed, list):
                        cats.update(parsed)
            if cats:
                allowed_categories = list(cats)

        # Internal capsules shared to these networks
        network_query = (
            select(CapsuleNetworkAccess.capsule_id)
            .join(KnowledgeCapsule, KnowledgeCapsule.id == CapsuleNetworkAccess.capsule_id)
            .where(
                CapsuleNetworkAccess.network_id.in_(network_ids),
                KnowledgeCapsule.owner_id == owner_id,
                KnowledgeCapsule.visibility.in_(["internal", "shareable"]),
                KnowledgeCapsule.is_archived == False,  # noqa: E712
                (KnowledgeCapsule.expires_at == None) | (KnowledgeCapsule.expires_at > now),  # noqa: E711
            )
        )
        # Apply category filter only if all pools are category_scoped
        if allowed_categories is not None:
            network_query = network_query.where(
                KnowledgeCapsule.category.in_(allowed_categories)
            )

        network_result = await db.execute(network_query)
        ids.extend(network_result.scalars().all())

    # Level 3: shareable — explicit grants to the requester (with expiry check)
    if requester_id:
        # Direct user grants
        grant_result = await db.execute(
            select(CapsuleShareGrant.capsule_id)
            .join(KnowledgeCapsule, KnowledgeCapsule.id == CapsuleShareGrant.capsule_id)
            .where(
                CapsuleShareGrant.grantee_user_id == requester_id,
                KnowledgeCapsule.owner_id == owner_id,
                KnowledgeCapsule.is_archived == False,  # noqa: E712
                # Check expiry: null means no expiry, or not yet expired
                (CapsuleShareGrant.expires_at == None) | (CapsuleShareGrant.expires_at > now),  # noqa: E711
            )
        )
        ids.extend(grant_result.scalars().all())

        # Network-based grants (grantee is a network the requester belongs to)
        if shared_networks:
            network_ids = [n.id for n in shared_networks]
            net_grant_result = await db.execute(
                select(CapsuleShareGrant.capsule_id)
                .join(KnowledgeCapsule, KnowledgeCapsule.id == CapsuleShareGrant.capsule_id)
                .where(
                    CapsuleShareGrant.grantee_network_id.in_(network_ids),
                    KnowledgeCapsule.owner_id == owner_id,
                    KnowledgeCapsule.is_archived == False,  # noqa: E712
                    (CapsuleShareGrant.expires_at == None) | (CapsuleShareGrant.expires_at > now),  # noqa: E711
                )
            )
            ids.extend(net_grant_result.scalars().all())

    return list(set(ids))


async def load_capsules_decrypted(
    db: AsyncSession, capsule_ids: list[str], owner_id_or_key
) -> list[dict]:
    """Load and decrypt capsules by ID. Marks superseded capsules.

    owner_id_or_key: either a user_id string (transit path) or bytes (legacy/compat).
    """
    if not capsule_ids:
        return []
    result = await db.execute(
        select(KnowledgeCapsule).where(KnowledgeCapsule.id.in_(capsule_ids))
    )
    capsules = result.scalars().all()
    decrypted = []
    for c in capsules:
        try:
            if isinstance(owner_id_or_key, str):
                content = transit_bridge.decrypt_text(owner_id_or_key, c.content_encrypted)
            elif owner_id_or_key == b"__transit__":
                # Sentinel from _TransitKeyStore — use capsule's owner_id
                content = transit_bridge.decrypt_text(c.owner_id, c.content_encrypted)
            else:
                # Legacy: raw bytes key
                from src.crypto import decrypt_text
                content = decrypt_text(c.content_encrypted, owner_id_or_key)
        except Exception:
            content = "Content is securely encrypted. Owner's vault key is required to view."
        decrypted.append({
            "id": c.id,
            "capsule_type": c.capsule_type,
            "title": c.title,
            "content": content,
            "tier": c.tier,
            "visibility": c.visibility,
            "emergency_accessible": c.emergency_accessible,
            "can_reshare": c.can_reshare,
            "category": c.category,
            "freshness": c.freshness,
            "expires_at": str(c.expires_at) if c.expires_at else None,
            "supersedes_id": c.supersedes_id,
            "authority_weight": c.authority_weight,
        })

    # Mark capsules that have been superseded by another capsule in the result set
    superseded_ids = {d["supersedes_id"] for d in decrypted if d.get("supersedes_id")}
    for d in decrypted:
        d["is_superseded"] = d["id"] in superseded_ids

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


async def query_agent_public(
    db: AsyncSession,
    target_user_id: str,
    question: str,
    from_did: str,
    from_pod: str,
    vault_keys=None,
    sensitivity_hint: str = "standard",
) -> dict:
    """Handle a cross-pod query at public trust level.

    Remote agents without a local connection get:
    - Trust level = "public" (only "open" capsules visible)
    - Citadel scanning on input AND output
    - Audit logging with remote agent DID
    - Read-only (no tools)
    """
    start = time.time()

    to_user = await db.get(User, target_user_id)
    if not to_user:
        return _error_result("remote", target_user_id, question, "User not found")

    agent_result = await db.execute(
        select(Agent).where(Agent.owner_id == target_user_id)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        return _error_result("remote", target_user_id, question, "Agent not found")

    # Citadel: scan input
    input_scan = await citadel.scan_input(question)
    if input_scan.decision == "BLOCK":
        latency = int((time.time() - start) * 1000)
        await log_event(
            db,
            actor_did=from_did,
            target_user_id=target_user_id,
            action="remote_query_blocked",
            event_type="query",
            decision="denied",
            details={"from_pod": from_pod, "citadel_score": input_scan.heuristic_score},
        )
        await db.commit()
        return _error_result(
            "remote", target_user_id, question,
            "Blocked: potential security threat detected",
            trust_level="public", latency_ms=latency,
        )

    # Public trust: only "open" capsules
    accessible_ids = await get_accessible_capsule_ids(
        db, target_user_id, "public", shared_networks=[],
    )

    # Semantic retrieval (no category scoping for public — search all)
    relevant_ids = embeddings.search_capsules(question, accessible_ids, top_k=5)
    if not relevant_ids:
        relevant_ids = accessible_ids[:5]

    # Decrypt capsules
    if not transit_bridge.has_key(target_user_id):
        return _error_result(
            "remote", target_user_id, question,
            "Vault key not available — target user needs to log in first",
            trust_level="public",
        )

    capsules = await load_capsules_decrypted(db, relevant_ids, target_user_id)

    # Agent responds (read-only, no tools)
    try:
        response_text = await agent_respond(
            agent=agent,
            question=question,
            trust_level="public",
            shared_networks=[],
            capsules=capsules,
            requester_name=f"Remote agent ({from_did[:20]}...)",
            owner_name=to_user.display_name,
            entity_type=to_user.user_type or "person",
            org_subtype=getattr(to_user, "org_subtype", None),
            agent_mode=getattr(to_user, "agent_mode", "private"),
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Remote query agent error for {target_user_id}: {e}")
        response_text = "I'm sorry, I encountered an issue processing your request."

    # Citadel: scan output (always public trust for remote queries)
    output_scan = await citadel.scan_output(response_text, trust_level="public")
    decision = "allowed"
    if not output_scan.is_safe:
        decision = "redacted"
        response_text = "This response was filtered by our security system."

    latency = int((time.time() - start) * 1000)

    # Log query
    query_record = Query(
        from_user_id="remote",
        to_user_id=target_user_id,
        question=question,
        trust_level="public",
        shared_networks="[]",
        response=response_text,
        decision=decision,
        citadel_input_score=input_scan.heuristic_score,
        citadel_input_decision=input_scan.decision,
        citadel_output_safe=output_scan.is_safe,
        citadel_output_findings=json.dumps(output_scan.findings) if output_scan.findings else None,
        latency_ms=latency,
    )
    db.add(query_record)

    # Audit log
    await log_event(
        db,
        actor_did=from_did,
        target_user_id=target_user_id,
        action="remote_query",
        event_type="query",
        query_id=query_record.id,
        decision=decision,
        details={"from_pod": from_pod, "trust_level": "public", "capsules_count": len(capsules)},
    )

    await db.commit()

    return {
        "from_did": from_did,
        "from_pod": from_pod,
        "to_user_id": target_user_id,
        "question": question,
        "trust_level": "public",
        "shared_networks": [],
        "response": response_text,
        "decision": decision,
        "latency_ms": latency,
    }


async def query_agent(
    db: AsyncSession,
    from_user_id: str,
    to_user_id: str,
    question: str,
    vault_keys=None,
    query_depth: int = 0,
    sensitivity_hint: str = "standard",
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
    5. Sonnet 4.5 agent responds (with or without tools)
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
        # Trust race condition fix: verify memberships still exist in DB
        if shared_networks:
            valid_net_ids = set()
            for net in shared_networks:
                exists = await db.execute(
                    select(NetworkMembership.id).where(
                        NetworkMembership.network_id == net.id,
                        NetworkMembership.user_id == from_user_id,
                    ).limit(1)
                )
                if exists.scalar_one_or_none():
                    valid_net_ids.add(net.id)
            if len(valid_net_ids) < len(shared_networks):
                shared_networks = [n for n in shared_networks if n.id in valid_net_ids]
                if not shared_networks:
                    trust_level = "public"
        network_names = [n.name for n in shared_networks]

    # 1b. Rate limit check (skip for self-query and agent sub-queries)
    if not is_self_query and query_depth == 0:
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

    # 3. Get accessible capsules (with context filter for self-query)
    ctx_filter = to_user.active_context if is_self_query else None
    accessible_ids = await get_accessible_capsule_ids(
        db, to_user_id, trust_level, shared_networks,
        requester_id=from_user_id if not is_self_query else None,
        context_filter=ctx_filter,
    )

    # 4. Semantic retrieval (category-scoped when possible)
    search_categories = None
    if shared_networks and not is_self_query:
        # Extract allowed categories from shared networks for scoped search
        has_standard = any(getattr(n, "pool_type", "standard") == "standard" for n in shared_networks)
        if not has_standard:
            cats = set()
            for n in shared_networks:
                raw = getattr(n, "shared_categories", None)
                if raw:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(parsed, list):
                        cats.update(parsed)
            if cats:
                search_categories = list(cats)

    relevant_ids = embeddings.search_capsules(question, accessible_ids, top_k=5, categories=search_categories)
    if not relevant_ids:
        relevant_ids = accessible_ids[:5]  # Fallback: use first 5

    # 5. Load and decrypt capsules
    if not transit_bridge.has_key(to_user_id):
        return _error_result(
            from_user_id, to_user_id, question,
            "Vault key not available — target user needs to log in first",
            trust_level=trust_level, shared_networks=network_names,
        )

    capsules = await load_capsules_decrypted(db, relevant_ids, to_user_id)

    # 6. Sonnet 4.5 agent responds
    actions = []
    routing_provider = "anthropic"
    try:
        if is_self_query:
            # Self-query: tools enabled (search, save, update)
            user_networks = await get_user_networks(db, to_user_id)
            tool_context = ToolContext(
                db=db,
                vault_key=b"__transit__",  # sentinel — tools use transit_bridge
                owner_id=to_user_id,
                owner_name=to_user.display_name,
                networks=user_networks,
                query_depth=query_depth,
                active_context=to_user.active_context or "all",
            )
            response_text, actions, routing_provider = await agent_respond_with_tools(
                agent=agent,
                question=question,
                capsules=capsules,
                owner_name=to_user.display_name,
                tool_context=tool_context,
                personality=agent.personality or "",
                entity_type=to_user.user_type or "person",
                org_subtype=getattr(to_user, "org_subtype", None),
                agent_mode=getattr(to_user, "agent_mode", "private"),
                sensitivity_hint=sensitivity_hint,
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
                entity_type=to_user.user_type or "person",
                org_subtype=getattr(to_user, "org_subtype", None),
                agent_mode=getattr(to_user, "agent_mode", "private"),
                sensitivity_hint=sensitivity_hint,
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Agent error for user {to_user_id}: {e}")
        response_text = "I'm sorry, I encountered an issue processing your request. Please try again."

    # 7. Citadel: scan output (skip for self-query)
    output_scan = None
    decision = "allowed"
    if not is_self_query:
        output_scan = await citadel.scan_output(response_text, trust_level=trust_level)
        if not output_scan.is_safe:
            decision = "redacted"
            response_text = "This response was filtered by our security system."

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

    # Include routing metadata for self-query (so UI can show provider pill)
    if is_self_query:
        result["routing"] = {"provider": routing_provider}

    return result
