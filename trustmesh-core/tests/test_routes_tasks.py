"""Tests for the task API endpoints (list, get) — user-scoped agent tasks."""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import async_session, init_db, drop_db
from src.models import AgentTask
from src.rate_limit import reset_rate_limits


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Reset DB and auth state for each test."""
    sessions.clear()
    _login_attempts.clear()
    reset_rate_limits()
    await drop_db()
    await init_db()
    yield
    await drop_db()


@pytest_asyncio.fixture
async def client():
    """Create an async test client."""
    from src.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


VALID_USER = {
    "username": "taskuser",
    "display_name": "Task Test User",
    "bio": "Testing tasks",
    "password": "SecureTestPass1!",
}

SECOND_USER = {
    "username": "otheruser",
    "display_name": "Other User",
    "bio": "Another user",
    "password": "SecureTestPass2!",
}


async def _create_user_and_get_id(client: AsyncClient, user_data: dict) -> str:
    """Create a user via the API and return their user ID."""
    resp = await client.post("/api/users", json=user_data)
    assert resp.status_code == 200
    return resp.json()["id"]


async def _insert_task(owner_id: str, title: str = "Test Task",
                       description: str = "A test task",
                       task_type: str = "search",
                       status: str = "pending") -> str:
    """Insert a task directly into the DB and return its ID."""
    task_id = str(uuid.uuid4())
    async with async_session() as db:
        task = AgentTask(
            id=task_id,
            owner_id=owner_id,
            title=title,
            description=description,
            task_type=task_type,
            status=status,
        )
        db.add(task)
        await db.commit()
    return task_id


@pytest.mark.asyncio
async def test_list_tasks_empty(client):
    """GET /api/users/{id}/tasks returns empty list when user has no tasks."""
    user_id = await _create_user_and_get_id(client, VALID_USER)

    resp = await client.get(f"/api/users/{user_id}/tasks")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_tasks_returns_owned_tasks(client):
    """GET /api/users/{id}/tasks returns tasks belonging to the user."""
    user_id = await _create_user_and_get_id(client, VALID_USER)

    task_id = await _insert_task(user_id, title="My Search Task", task_type="search")

    resp = await client.get(f"/api/users/{user_id}/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == task_id
    assert data[0]["title"] == "My Search Task"
    assert data[0]["task_type"] == "search"
    assert data[0]["status"] == "pending"
    assert data[0]["owner_id"] == user_id


@pytest.mark.asyncio
async def test_get_task_by_id(client):
    """GET /api/tasks/{task_id} returns the task details for the owner."""
    user_id = await _create_user_and_get_id(client, VALID_USER)

    task_id = await _insert_task(user_id, title="Detailed Task",
                                 description="With a description",
                                 task_type="compile", status="in_progress")

    resp = await client.get(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == task_id
    assert data["title"] == "Detailed Task"
    assert data["description"] == "With a description"
    assert data["task_type"] == "compile"
    assert data["status"] == "in_progress"


@pytest.mark.asyncio
async def test_get_task_not_found(client):
    """GET /api/tasks/{task_id} returns 404 for a nonexistent task."""
    await _create_user_and_get_id(client, VALID_USER)

    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/tasks/{fake_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_tasks_forbidden_for_other_user(client):
    """GET /api/users/{id}/tasks returns 403 when requesting another user's tasks."""
    user_id = await _create_user_and_get_id(client, VALID_USER)
    await _insert_task(user_id, title="Private Task")

    # Logout and login as a different user
    await client.post("/api/auth/logout")
    other_id = await _create_user_and_get_id(client, SECOND_USER)

    # Try to list the first user's tasks as the second user
    resp = await client.get(f"/api/users/{user_id}/tasks")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_task_forbidden_for_other_user(client):
    """GET /api/tasks/{task_id} returns 403 when a different user tries to access it."""
    user_id = await _create_user_and_get_id(client, VALID_USER)
    task_id = await _insert_task(user_id, title="Secret Task")

    # Logout and login as a different user
    await client.post("/api/auth/logout")
    await _create_user_and_get_id(client, SECOND_USER)

    # Try to get the first user's task as the second user
    resp = await client.get(f"/api/tasks/{task_id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_tasks_unauthenticated(client):
    """GET /api/users/{id}/tasks returns 401 without a session cookie."""
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/users/{fake_id}/tasks")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_task_unauthenticated(client):
    """GET /api/tasks/{task_id} returns 401 without a session cookie."""
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/tasks/{fake_id}")
    assert resp.status_code == 401
