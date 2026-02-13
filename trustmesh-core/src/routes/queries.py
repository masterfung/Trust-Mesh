"""Inter-agent query routes — the core of TrustMesh."""

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db, async_session
from src.gossip import query_agent
from src.models import Agent, Notification, Query, User
from src.schemas import QueryCreate, QueryResponse, CitadelResult

router = APIRouter(prefix="/api", tags=["queries"])


@router.post("/query")
async def create_query(data: QueryCreate, db: AsyncSession = Depends(get_db),
                       auth_user_id: str = Depends(get_current_user_id)):
    """Query another user's agent. The core TrustMesh operation."""
    if auth_user_id != data.from_user_id:
        raise HTTPException(403, "Access denied")
    from src.main import vault_keys

    result = await query_agent(
        db=db,
        from_user_id=data.from_user_id,
        to_user_id=data.to_user_id,
        question=data.question,
        vault_keys=vault_keys,
    )
    return result


@router.post("/query/stream")
async def create_query_stream(data: QueryCreate,
                              auth_user_id: str = Depends(get_current_user_id)):
    """Streaming query endpoint — returns SSE events as the agent responds."""
    if auth_user_id != data.from_user_id:
        raise HTTPException(403, "Access denied")
    from src.main import vault_keys
    from src import citadel, embeddings
    from src.agents import (
        ToolContext, agent_respond_streaming, agent_respond_with_tools_streaming,
        detect_sensitivity,
    )
    from src.gossip import (
        get_accessible_capsule_ids, get_user_networks, load_capsules_decrypted,
    )
    from src.trust import resolve_trust_level
    from src.rate_limit import check_query_rate, record_query

    async def event_generator():
        start = time.time()
        is_self_query = data.from_user_id == data.to_user_id
        full_text = ""

        async with async_session() as db:
            from_user = await db.get(User, data.from_user_id)
            to_user = await db.get(User, data.to_user_id)
            if not from_user or not to_user:
                yield f"data: {json.dumps({'type': 'error', 'data': 'User not found'})}\n\n"
                return

            agent_result = await db.execute(
                select(Agent).where(Agent.owner_id == data.to_user_id)
            )
            agent = agent_result.scalar_one_or_none()
            if not agent:
                yield f"data: {json.dumps({'type': 'error', 'data': 'Agent not found'})}\n\n"
                return

            # Resolve trust
            if is_self_query:
                trust_level = "private"
                shared_networks = []
                network_names = []
            else:
                trust_level, shared_networks = await resolve_trust_level(db, data.from_user_id, data.to_user_id)
                network_names = [n.name for n in shared_networks]

            # Rate limit
            if not is_self_query:
                rate_ok, rate_reason = check_query_rate(data.from_user_id, data.to_user_id, trust_level)
                if not rate_ok:
                    yield f"data: {json.dumps({'type': 'error', 'data': rate_reason})}\n\n"
                    return

            # Citadel input scan
            if not is_self_query:
                input_scan = await citadel.scan_input(data.question)
                if input_scan.decision == "BLOCK":
                    yield f"data: {json.dumps({'type': 'error', 'data': 'Blocked: potential security threat'})}\n\n"
                    return
            else:
                input_scan = None

            # Send metadata
            yield f"data: {json.dumps({'type': 'meta', 'trust_level': trust_level, 'shared_networks': network_names})}\n\n"

            # Get capsules
            accessible_ids = await get_accessible_capsule_ids(db, data.to_user_id, trust_level, shared_networks)
            relevant_ids = embeddings.search_capsules(data.question, accessible_ids, top_k=5)
            if not relevant_ids:
                relevant_ids = accessible_ids[:5]

            vault_key = vault_keys.get(data.to_user_id)
            if not vault_key:
                yield f"data: {json.dumps({'type': 'error', 'data': 'Vault key not available'})}\n\n"
                return

            capsules = await load_capsules_decrypted(db, relevant_ids, vault_key)

            # Stream the response
            actions = []
            try:
                if is_self_query:
                    user_networks = await get_user_networks(db, data.to_user_id)
                    tool_context = ToolContext(
                        db=db,
                        vault_key=vault_key,
                        owner_id=data.to_user_id,
                        owner_name=to_user.display_name,
                        networks=user_networks,
                    )
                    history = [{"role": m.role, "content": m.content} for m in (data.conversation_history or [])]
                    async for event_type, event_data in agent_respond_with_tools_streaming(
                        agent=agent,
                        question=data.question,
                        capsules=capsules,
                        owner_name=to_user.display_name,
                        tool_context=tool_context,
                        conversation_history=history,
                    ):
                        if event_type == "text":
                            full_text += event_data
                            yield f"data: {json.dumps({'type': 'text', 'data': event_data})}\n\n"
                        elif event_type == "tool":
                            yield f"data: {json.dumps({'type': 'tool', 'data': event_data})}\n\n"
                        elif event_type == "actions":
                            actions = event_data
                else:
                    history = [{"role": m.role, "content": m.content} for m in (data.conversation_history or [])]
                    async for chunk in agent_respond_streaming(
                        agent=agent,
                        question=data.question,
                        trust_level=trust_level,
                        shared_networks=shared_networks,
                        capsules=capsules,
                        requester_name=from_user.display_name,
                        owner_name=to_user.display_name,
                        conversation_history=history,
                    ):
                        full_text += chunk
                        yield f"data: {json.dumps({'type': 'text', 'data': chunk})}\n\n"
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception("Agent streaming error")
                full_text = "Agent encountered an error processing your request."
                yield f"data: {json.dumps({'type': 'error', 'data': 'Agent encountered an error processing your request.'})}\n\n"

            # Citadel output scan
            decision = "allowed"
            output_scan = None
            if not is_self_query:
                output_scan = await citadel.scan_output(full_text)
                if not output_scan.is_safe:
                    decision = "redacted"

            latency = int((time.time() - start) * 1000)

            if not is_self_query:
                record_query(data.from_user_id, data.to_user_id)

            # Log query
            query_record = Query(
                from_user_id=data.from_user_id,
                to_user_id=data.to_user_id,
                question=data.question,
                trust_level=trust_level,
                shared_networks=json.dumps(network_names),
                response=full_text,
                decision=decision,
                citadel_input_score=input_scan.heuristic_score if input_scan else None,
                citadel_input_decision=input_scan.decision if input_scan else None,
                citadel_output_safe=output_scan.is_safe if output_scan else None,
                citadel_output_findings=json.dumps(output_scan.findings) if output_scan and output_scan.findings else None,
                latency_ms=latency,
            )
            db.add(query_record)
            await db.flush()

            if not is_self_query:
                notification = Notification(
                    user_id=data.to_user_id,
                    notification_type="query_received",
                    title=f"Query from {from_user.display_name}",
                    body=data.question[:200],
                    related_id=query_record.id,
                )
                db.add(notification)

            await db.commit()

            # Send final done event with metadata
            yield f"data: {json.dumps({'type': 'done', 'id': query_record.id, 'decision': decision, 'latency_ms': latency, 'trust_level': trust_level, 'shared_networks': network_names, 'agent_actions': actions})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/users/{user_id}/queries", response_model=list[QueryResponse])
async def list_queries(user_id: str, db: AsyncSession = Depends(get_db),
                       auth_user_id: str = Depends(get_current_user_id)):
    """List query history (sent and received)."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    result = await db.execute(
        select(Query)
        .where(or_(Query.from_user_id == user_id, Query.to_user_id == user_id))
        .order_by(Query.created_at.desc())
        .limit(50)
    )
    queries = result.scalars().all()
    responses = []
    for q in queries:
        shared = json.loads(q.shared_networks) if q.shared_networks else []
        citadel_input = None
        if q.citadel_input_decision:
            citadel_input = CitadelResult(
                score=q.citadel_input_score,
                decision=q.citadel_input_decision,
            )
        citadel_output = None
        if q.citadel_output_safe is not None:
            findings = json.loads(q.citadel_output_findings) if q.citadel_output_findings else []
            citadel_output = CitadelResult(
                is_safe=q.citadel_output_safe,
                findings=findings,
            )
        responses.append(QueryResponse(
            id=q.id,
            from_user_id=q.from_user_id,
            to_user_id=q.to_user_id,
            question=q.question,
            trust_level=q.trust_level,
            shared_networks=shared,
            response=q.response,
            decision=q.decision,
            citadel_input=citadel_input,
            citadel_output=citadel_output,
            latency_ms=q.latency_ms,
            created_at=q.created_at,
        ))
    return responses
