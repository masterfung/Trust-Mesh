"""Multi-pod orchestrator: wires 19 pods together after they're running.

Phases:
  1. Wait for all pods to be healthy
  2. Register all agents with the public registry (port 8100)
  3. Establish peer connections between pods that need to communicate
  4. Form pools via pool-sync (creates ghost users + networks)
  5. Verify federation state

Usage:
    cd trustmesh-core && uv run python orchestrate.py
"""

import asyncio
import os
import sys

import httpx

POOL_SYNC_SECRET = os.getenv("TRUSTMESH_POOL_SYNC_SECRET", "")
FEDERATION_HEADERS = {"X-Pool-Sync-Secret": POOL_SYNC_SECRET} if POOL_SYNC_SECRET else {}

# ── Pod topology ──

REGISTRY_URL = "http://localhost:8100"

# Same mapping as seed_multi.py
PODS = {
    "sarah":     {"port": 8001, "username": "molly",       "display_name": "Molly Johnson"},
    "mike":      {"port": 8002, "username": "peter",       "display_name": "Peter Johnson"},
    "emma":      {"port": 8003, "username": "jane",        "display_name": "Jane Johnson"},
    "grandma":   {"port": 8004, "username": "grandmarose", "display_name": "Grandma Rose"},
    "dr_chen":   {"port": 8005, "username": "dr_lee",      "display_name": "Dr. Sarah Lee"},
    "tom":       {"port": 8006, "username": "kyle",        "display_name": "Kyle Rivera"},
    "lisa":      {"port": 8007, "username": "amy",         "display_name": "Amy Torres"},
    "priya":     {"port": 8008, "username": "dorothy",     "display_name": "Dorothy Park"},
    "james":     {"port": 8009, "username": "nurse_davis", "display_name": "Nurse Rachel Davis"},
    "maria":     {"port": 8010, "username": "emt_johnson", "display_name": "EMT Mike Johnson"},
    "techcorp":  {"port": 8011, "username": "sparkleclean",       "display_name": "SparkleClean Residential"},
    "hospital":  {"port": 8012, "username": "riverside_hospital", "display_name": "Riverside General Hospital"},
    "music":     {"port": 8013, "username": "acetutor",           "display_name": "AceTutor SAT Prep"},
    "city":      {"port": 8014, "username": "riverside_gov",      "display_name": "City of Riverside"},
    "insurance": {"port": 8015, "username": "handypro",           "display_name": "HandyPro Home Services"},
    "dance":     {"port": 8016, "username": "riverside_ambulance","display_name": "Riverside City Ambulance"},
}

def pod_url(key: str) -> str:
    return f"http://localhost:{PODS[key]['port']}"


# ── Peer connections (which pods need to talk to each other) ──
# Based on CONNECTIONS from seed.py, mapped to pod keys
PEER_CONNECTIONS = [
    # Johnson family
    ("mike", "sarah"),   # peter <-> molly
    ("mike", "emma"),    # peter <-> jane
    ("mike", "grandma"), # peter <-> grandmarose
    ("sarah", "emma"),   # molly <-> jane
    ("sarah", "grandma"),# molly <-> grandmarose
    ("emma", "grandma"), # jane <-> grandmarose
    # Work
    ("sarah", "tom"),    # molly <-> kyle (TechCorp)
    # Neighbors
    ("mike", "priya"),   # peter <-> dorothy (via linda role)
    ("sarah", "priya"),  # molly <-> dorothy
    # Friends
    ("emma", "lisa"),    # jane <-> amy
    # Grandma's circle
    ("grandma", "priya"),# grandmarose <-> dorothy
    # Healthcare
    ("dr_chen", "james"),   # dr_lee <-> nurse_davis
    ("dr_chen", "maria"),   # dr_lee <-> emt_johnson
    ("james", "maria"),     # nurse_davis <-> emt_johnson
    ("dr_chen", "hospital"),# dr_lee <-> riverside_hospital
    ("james", "hospital"),  # nurse_davis <-> riverside_hospital
    ("maria", "dance"),     # emt_johnson <-> riverside_ambulance
    ("maria", "hospital"),  # emt_johnson <-> riverside_hospital
]

# ── Pool definitions (cross-pod networks) ──
# Maps to NETWORKS from seed.py
POOLS = [
    {
        "name": "The Johnsons",
        "type": "family",
        "pool_type": "standard",
        "context": "personal",
        "description": "Johnson family knowledge sharing.",
        "members": ["mike", "sarah", "emma"],  # peter, molly, jane (bill mapped away)
    },
    {
        "name": "TechCorp PM Team",
        "type": "team",
        "pool_type": "category_scoped",
        "shared_categories": ["work"],
        "context": "work",
        "description": "TechCorp project management team.",
        "members": ["sarah", "tom"],  # molly, kyle
    },
    {
        "name": "Rose's Care Circle",
        "type": "family",
        "pool_type": "category_scoped",
        "shared_categories": ["health"],
        "context": "personal",
        "description": "Coordinating Grandma Rose's care.",
        "members": ["sarah", "mike", "grandma", "priya"],  # molly, peter, rose, dorothy
    },
    {
        "name": "Lincoln High Soccer",
        "type": "friends",
        "pool_type": "standard",
        "context": "personal",
        "description": "Varsity soccer team.",
        "members": ["emma", "lisa"],  # jane, amy
    },
    {
        "name": "Riverside ER Team",
        "type": "team",
        "pool_type": "category_scoped",
        "shared_categories": ["health", "work"],
        "context": "work",
        "description": "Hospital emergency department staff.",
        "members": ["dr_chen", "james", "maria"],  # dr_lee, nurse_davis, emt_johnson
    },
    {
        "name": "Riverside Neighbors",
        "type": "friends",
        "pool_type": "standard",
        "context": "personal",
        "description": "Neighborhood community.",
        "members": ["mike", "sarah"],  # peter, molly (linda mapped to priya)
    },
    {
        "name": "Riverside Bridge Club",
        "type": "friends",
        "pool_type": "standard",
        "context": "personal",
        "description": "Weekly bridge games.",
        "members": ["grandma", "priya"],  # grandmarose, dorothy
    },
]


async def wait_for_pods(client: httpx.AsyncClient) -> dict[str, dict]:
    """Phase 1: Wait for all pods to be healthy. Returns pod info for each."""
    print("\n=== Phase 1: Waiting for pods ===\n")
    pod_info = {}
    max_retries = 30

    for key, conf in PODS.items():
        url = f"http://localhost:{conf['port']}"
        for attempt in range(max_retries):
            try:
                r = await client.get(f"{url}/health", timeout=3.0)
                if r.status_code == 200:
                    # Get pod info (agent DID etc.)
                    info_r = await client.get(f"{url}/api/pod", timeout=5.0)
                    info = info_r.json() if info_r.status_code == 200 else {}
                    pod_info[key] = info
                    print(f"  OK  :{conf['port']}  {conf['display_name']}")
                    break
            except (httpx.RequestError, httpx.HTTPStatusError):
                pass
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
        else:
            print(f"  FAIL :{conf['port']}  {conf['display_name']} (timeout after {max_retries}s)")

    print(f"\n  {len(pod_info)}/{len(PODS)} pods healthy")
    return pod_info


async def _fetch_user_details(client: httpx.AsyncClient, port: int, username: str) -> dict:
    """Fetch user bio and skills from a pod's /api/users endpoint."""
    try:
        r = await client.get(f"http://localhost:{port}/api/users", timeout=5.0)
        if r.status_code == 200:
            users = r.json()
            for u in users:
                if u.get("username") == username:
                    skills = []
                    profile = u.get("profile_data") or {}
                    if isinstance(profile, dict):
                        for s in profile.get("skills", []):
                            if isinstance(s, dict) and s.get("name"):
                                skills.append(s["name"])
                            elif isinstance(s, str):
                                skills.append(s)
                        for s in profile.get("services", []):
                            if isinstance(s, dict) and s.get("name"):
                                skills.append(s["name"])
                    return {"bio": u.get("bio", ""), "capabilities": skills[:6]}
    except (httpx.RequestError, Exception):
        pass
    return {"bio": "", "capabilities": []}


async def register_with_registry(client: httpx.AsyncClient, pod_info: dict[str, dict]):
    """Phase 2: Register all agents with the public registry."""
    print("\n=== Phase 2: Registering with public registry ===\n")

    # Check registry is up
    try:
        r = await client.get(f"{REGISTRY_URL}/api/health", timeout=3.0)
        if r.status_code != 200:
            print("  Registry not available, skipping registration")
            return
    except httpx.RequestError:
        print("  Registry not available, skipping registration")
        return

    registered = 0
    for key, info in pod_info.items():
        agents = info.get("agents", [])
        # Fetch bio + skills from the pod
        details = await _fetch_user_details(client, PODS[key]["port"], PODS[key]["username"])
        for agent in agents:
            try:
                await client.post(f"{REGISTRY_URL}/api/register", json={
                    "name": agent.get("name", PODS[key]["display_name"]),
                    "did": agent.get("did", ""),
                    "pod_url": f"http://localhost:{PODS[key]['port']}",
                    "entity_type": agent.get("user_type", "person"),
                    "capabilities": details["capabilities"],
                    "username": agent.get("owner_username", PODS[key]["username"]),
                    "display_name": agent.get("owner_display_name", PODS[key]["display_name"]),
                    "bio": details["bio"],
                }, timeout=5.0)
                registered += 1
            except httpx.RequestError:
                pass
        print(f"  Registered {len(agents)} agent(s) from :{PODS[key]['port']} {PODS[key]['display_name']}")

    print(f"\n  {registered} total agents registered")


async def establish_peers(client: httpx.AsyncClient, pod_info: dict[str, dict]):
    """Phase 3: Establish peer connections between pods."""
    print("\n=== Phase 3: Establishing peer connections ===\n")
    connected = 0
    for pod_a, pod_b in PEER_CONNECTIONS:
        if pod_a not in pod_info or pod_b not in pod_info:
            continue
        url_a = pod_url(pod_a)
        url_b = pod_url(pod_b)
        try:
            r = await client.post(f"{url_a}/api/pod/peers", json={"url": url_b}, timeout=30.0, headers=FEDERATION_HEADERS)
            if r.status_code in (200, 400):  # 400 = already peered or self-peer
                connected += 1
                status = "OK" if r.status_code == 200 else "exists"
                print(f"  {status}  {PODS[pod_a]['display_name']} <-> {PODS[pod_b]['display_name']}")
            else:
                detail = ""
                try:
                    detail = r.json().get("detail", r.text[:100])
                except Exception:
                    detail = r.text[:100]
                print(f"  FAIL {PODS[pod_a]['display_name']} <-> {PODS[pod_b]['display_name']}: HTTP {r.status_code} {detail}")
        except httpx.RequestError as e:
            print(f"  FAIL {PODS[pod_a]['display_name']} <-> {PODS[pod_b]['display_name']}: {e}")

    print(f"\n  {connected}/{len(PEER_CONNECTIONS)} peer connections established")


async def form_pools(client: httpx.AsyncClient, pod_info: dict[str, dict]):
    """Phase 4: Form pools via pool-sync on each member pod."""
    print("\n=== Phase 4: Forming pools ===\n")

    for pool in POOLS:
        members_data = []
        for member_key in pool["members"]:
            if member_key not in pod_info:
                continue
            agents = pod_info[member_key].get("agents", [])
            did = agents[0]["did"] if agents else ""
            members_data.append({
                "did": did,
                "pod_url": pod_url(member_key),
                "username": PODS[member_key]["username"],
                "display_name": PODS[member_key]["display_name"],
            })

        synced = 0
        for member_key in pool["members"]:
            if member_key not in pod_info:
                continue
            url = pod_url(member_key)
            try:
                r = await client.post(f"{url}/api/pod/pool-sync", json={
                    "network_name": pool["name"],
                    "network_type": pool["type"],
                    "pool_type": pool.get("pool_type", "standard"),
                    "shared_categories": pool.get("shared_categories"),
                    "context": pool.get("context", "personal"),
                    "description": pool.get("description", ""),
                    "creator_pod_url": pod_url(pool["members"][0]),
                    "members": members_data,
                }, timeout=10.0, headers=FEDERATION_HEADERS)
                if r.status_code == 200:
                    result = r.json()
                    synced += 1
                    print(f"    :{PODS[member_key]['port']} synced ({result.get('ghost_members_added', 0)} ghosts)")
                else:
                    print(f"    :{PODS[member_key]['port']} FAIL ({r.status_code}: {r.text[:100]})")
            except httpx.RequestError as e:
                print(f"    :{PODS[member_key]['port']} FAIL ({e})")

        print(f"  Pool '{pool['name']}': {synced}/{len(pool['members'])} members synced")

    print()


async def verify_federation(client: httpx.AsyncClient, pod_info: dict[str, dict]):
    """Phase 5: Verify the federation state."""
    print("=== Phase 5: Verification ===\n")

    # Check registry
    try:
        r = await client.get(f"{REGISTRY_URL}/api/agents", timeout=5.0)
        if r.status_code == 200:
            data = r.json()
            print(f"  Registry: {data['count']} agents registered")
    except httpx.RequestError:
        print("  Registry: unavailable")

    # Spot-check a few pods
    for key in ["sarah", "grandma", "dr_chen"]:
        if key not in pod_info:
            continue
        url = pod_url(key)
        try:
            # Check peers
            r = await client.get(f"{url}/api/pod/peers", timeout=5.0)
            peers = r.json().get("peers", []) if r.status_code == 200 else []
            active_peers = [p for p in peers if p["status"] == "active"]
            print(f"  :{PODS[key]['port']} {PODS[key]['display_name']}: {len(active_peers)} active peers")
        except httpx.RequestError:
            pass

    print("\n=== Federation complete ===\n")


async def main():
    """Run the full orchestration pipeline."""
    print("\n" + "=" * 50)
    print("  TrustMesh Multi-Pod Orchestrator")
    print("=" * 50)

    async with httpx.AsyncClient() as client:
        # Phase 1: Wait for pods
        pod_info = await wait_for_pods(client)
        if len(pod_info) < len(PODS):
            print(f"\nWARNING: Only {len(pod_info)}/{len(PODS)} pods are healthy")
            if len(pod_info) == 0:
                print("No pods available. Run: ./multi-pod.sh start")
                sys.exit(1)

        # Phase 2: Register with public registry
        await register_with_registry(client, pod_info)

        # Phase 3: Establish peer connections
        await establish_peers(client, pod_info)

        # Phase 4: Form pools
        await form_pools(client, pod_info)

        # Phase 5: Verify
        await verify_federation(client, pod_info)


if __name__ == "__main__":
    asyncio.run(main())
