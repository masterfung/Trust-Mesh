"""Intake agent onboarding route — conversational setup for new users."""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from src.auth import get_current_user_id
from src.database import async_session
from src.models import Agent, User

router = APIRouter(prefix="/api", tags=["intake"])


class IntakeMessage(BaseModel):
    message: str
    conversation_history: list[dict] = []  # [{role, content}, ...]


@router.post("/users/{user_id}/intake")
async def intake_step(user_id: str, data: IntakeMessage,
                      auth_user_id: str = Depends(get_current_user_id)):
    """Run one step of the intake onboarding conversation.

    The frontend sends the user's message + full conversation history.
    The agent responds, potentially saving capsules via tools.
    Returns SSE stream with text chunks and actions.
    """
    from src import transit_bridge
    from src.agents import ToolContext, run_intake_step
    from src.gossip import get_user_networks

    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    async def event_generator():
        async with async_session() as db:
            user = await db.get(User, user_id)
            if not user:
                yield f"data: {json.dumps({'type': 'error', 'data': 'User not found'})}\n\n"
                return

            agent_result = await db.execute(
                select(Agent).where(Agent.owner_id == user_id)
            )
            agent = agent_result.scalar_one_or_none()
            if not agent:
                yield f"data: {json.dumps({'type': 'error', 'data': 'Agent not found'})}\n\n"
                return

            if not transit_bridge.has_key(user_id):
                yield f"data: {json.dumps({'type': 'error', 'data': 'Vault key not available'})}\n\n"
                return

            user_networks = await get_user_networks(db, user_id)
            tool_context = ToolContext(
                db=db,
                vault_key=b"",  # unused — transit_bridge handles encryption
                owner_id=user_id,
                owner_name=user.display_name,
                networks=user_networks,
            )

            # Determine the message to send
            message = data.message
            if not message.strip() and not data.conversation_history:
                # First message — trigger the agent to start the conversation
                message = (
                    f"Hi! I just signed up for TrustMesh. My name is {user.display_name}."
                    + (f" Here's a bit about me: {user.bio}" if user.bio else "")
                )

            try:
                response_text, actions = await run_intake_step(
                    owner_name=user.display_name,
                    user_message=message,
                    conversation_history=data.conversation_history,
                    tool_context=tool_context,
                )

                # Commit capsules saved by the agent tools
                await db.commit()

                # Stream the response in chunks for a nice UX
                chunk_size = 4
                words = response_text.split(" ")
                for i in range(0, len(words), chunk_size):
                    chunk = " ".join(words[i:i + chunk_size])
                    if i > 0:
                        chunk = " " + chunk
                    yield f"data: {json.dumps({'type': 'text', 'data': chunk})}\n\n"

                # Send actions (capsules created)
                if actions:
                    yield f"data: {json.dumps({'type': 'actions', 'data': actions})}\n\n"

                yield f"data: {json.dumps({'type': 'done'})}\n\n"

            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
