"""Inter-agent query routes — the core of TrustMesh."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.gossip import query_agent
from src.models import Query
from src.schemas import QueryCreate, QueryResponse, CitadelResult

router = APIRouter(prefix="/api", tags=["queries"])


@router.post("/query")
async def create_query(data: QueryCreate, db: AsyncSession = Depends(get_db)):
    """Query another user's agent. The core TrustMesh operation."""
    from src.main import vault_keys

    result = await query_agent(
        db=db,
        from_user_id=data.from_user_id,
        to_user_id=data.to_user_id,
        question=data.question,
        vault_keys=vault_keys,
    )
    return result


@router.get("/users/{user_id}/queries", response_model=list[QueryResponse])
async def list_queries(user_id: str, db: AsyncSession = Depends(get_db)):
    """List query history (sent and received)."""
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
