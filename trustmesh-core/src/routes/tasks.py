"""Agent task routes — trackable work items for agents."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db
from src.models import AgentTask
from src.schemas import AgentTaskResponse

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/users/{user_id}/tasks", response_model=list[AgentTaskResponse])
async def list_user_tasks(user_id: str, db: AsyncSession = Depends(get_db),
                          auth_user_id: str = Depends(get_current_user_id)):
    """List tasks for a user, newest first."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")
    result = await db.execute(
        select(AgentTask)
        .where(AgentTask.owner_id == user_id)
        .order_by(AgentTask.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()


@router.get("/tasks/{task_id}", response_model=AgentTaskResponse)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db),
                   auth_user_id: str = Depends(get_current_user_id)):
    """Get task details."""
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.owner_id != auth_user_id:
        raise HTTPException(403, "Access denied")
    return task
