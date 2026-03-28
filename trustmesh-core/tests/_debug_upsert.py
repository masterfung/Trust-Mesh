"""Debug script to reproduce the upsert 404 issue."""
import asyncio
import os
import uuid

os.environ["TRUSTMESH_DEV_MODE"] = "1"
os.environ["TRUSTMESH_DISABLE_CSRF"] = "1"

_USER = {"username": "ncmemtest2", "display_name": "Test", "bio": "", "password": "NullClawPass1x"}


async def run_one():
    from src.auth import _login_attempts, sessions
    from src.database import drop_db, init_db
    from src.main import vault_keys
    from httpx import ASGITransport, AsyncClient

    sessions.clear()
    _login_attempts.clear()
    vault_keys.clear()
    await drop_db()
    await init_db()

    from src.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/users", json=_USER)
        if "id" not in r.json():
            print(f"User create failed: {r.status_code} {r.text[:200]}")
            return False
        user_id = r.json()["id"]
        await client.post("/api/auth/login", json={"username": _USER["username"], "password": _USER["password"]})
        r3 = await client.post(f"/api/users/{user_id}/channel-tokens", json={"name": "test", "scopes": ["memory"]})
        token = r3.json()["raw_token"]
        headers = {"authorization": f"Bearer {token}"}
        key = str(uuid.uuid4())
        ns = _USER["username"]
        r4 = await client.put(f"/api/memory/{ns}/memories/{key}", json={"content": "original", "category": "core"}, headers=headers)
        r5 = await client.put(f"/api/memory/{ns}/memories/{key}", json={"content": "updated", "category": "core"}, headers=headers)
        if r5.status_code != 200:
            print(f"FAIL: {r5.status_code} {r5.text[:200]}")
            return False
        return True


async def main():
    results = []
    for i in range(20):
        results.append(await run_one())
    print(f"Pass: {sum(results)}/20")


asyncio.run(main())
