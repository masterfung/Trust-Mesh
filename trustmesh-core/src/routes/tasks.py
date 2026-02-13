"""Agent task routes — trackable work items for agents."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models import AgentTask
from src.schemas import AgentTaskResponse

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/users/{user_id}/tasks", response_model=list[AgentTaskResponse])
async def list_user_tasks(user_id: str, db: AsyncSession = Depends(get_db)):
    """List tasks for a user, newest first."""
    result = await db.execute(
        select(AgentTask)
        .where(AgentTask.owner_id == user_id)
        .order_by(AgentTask.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()


@router.get("/tasks/{task_id}", response_model=AgentTaskResponse)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """Get task details."""
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task
