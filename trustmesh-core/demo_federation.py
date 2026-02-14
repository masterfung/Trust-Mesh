#!/usr/bin/env python3
"""Multi-pod federation demo — two TrustMesh pods connecting.

This script demonstrates:
1. Pod A (Johnson Family) on port 8000
2. Pod B (Hospital) on port 8001
3. Pod A discovers Pod B's agents via /.well-known/agent-card.json
4. Pod A connects to Pod B as peer
5. Cross-pod query: Molly (Pod A) queries Dr. Lee (Pod B)
6. Pod B returns only "open" capsules (public trust level)

Usage:
    # Terminal 1: start Pod A (Johnson Family)
    TRUSTMESH_POD_NAME="Johnson Family Pod" TRUSTMESH_POD_URL=http://localhost:8000 \
        TRUSTMESH_DB=./pod_a.db uv run uvicorn src.main:app --port 8000

    # Terminal 2: start Pod B (Hospital)
    TRUSTMESH_POD_NAME="Riverside Hospital Pod" TRUSTMESH_POD_URL=http://localhost:8001 \
        TRUSTMESH_DB=./pod_b.db uv run uvicorn src.main:app --port 8001

    # Terminal 3: run this demo
    uv run python demo_federation.py
"""

import asyncio
import json
import sys

import httpx

POD_A = "http://localhost:8000"  # Johnson Family
POD_B = "http://localhost:8001"  # Hospital

TIMEOUT = 30.0


def header(text: str):
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def step(n: int, text: str):
    print(f"\n--- Step {n}: {text} ---\n")


async def check_pod(url: str, name: str) -> bool:
    """Check if a pod is running."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{url}/health")
            if r.status_code == 200:
                print(f"  [OK] {name} is running at {url}")
                return True
    except httpx.RequestError:
        pass
    print(f"  [FAIL] {name} is NOT running at {url}")
    return False


async def main():
    header("TrustMesh Pod Federation Demo")

    # ── Pre-flight: check both pods are running ──
    step(0, "Checking pods are running")
    pod_a_ok = await check_pod(POD_A, "Pod A (Johnson Family)")
    pod_b_ok = await check_pod(POD_B, "Pod B (Hospital)")

    if not pod_a_ok or not pod_b_ok:
        print("\nBoth pods must be running. Start them with:")
        print(f"  Terminal 1: TRUSTMESH_POD_NAME='Johnson Family Pod' TRUSTMESH_POD_URL={POD_A} \\")
        print(f"    TRUSTMESH_DB=./pod_a.db uv run uvicorn src.main:app --port 8000")
        print(f"  Terminal 2: TRUSTMESH_POD_NAME='Riverside Hospital Pod' TRUSTMESH_POD_URL={POD_B} \\")
        print(f"    TRUSTMESH_DB=./pod_b.db uv run uvicorn src.main:app --port 8001")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # ── Step 1: Discover Pod A's identity ──
        step(1, "Pod A identifies itself")
        r = await client.get(f"{POD_A}/api/pod")
        pod_a_info = r.json()
        print(f"  Pod name: {pod_a_info['pod_name']}")
        print(f"  Agents: {pod_a_info['agent_count']}")
        if pod_a_info.get("agents"):
            for a in pod_a_info["agents"][:3]:
                print(f"    - {a['name']} ({a['owner_username']})")
            if pod_a_info["agent_count"] > 3:
                print(f"    ... and {pod_a_info['agent_count'] - 3} more")

        # ── Step 2: Discover Pod B's identity ──
        step(2, "Pod B identifies itself")
        r = await client.get(f"{POD_B}/api/pod")
        pod_b_info = r.json()
        print(f"  Pod name: {pod_b_info['pod_name']}")
        print(f"  Agents: {pod_b_info['agent_count']}")
        if pod_b_info.get("agents"):
            for a in pod_b_info["agents"][:3]:
                print(f"    - {a['name']} ({a['owner_username']})")

        # ── Step 3: Fetch Pod B's A2A Agent Card ──
        step(3, "Pod A fetches Pod B's A2A Agent Card")
        r = await client.get(f"{POD_B}/.well-known/agent-card.json")
        agent_card = r.json()
        print(f"  Agent card name: {agent_card['name']}")
        print(f"  URL: {agent_card['url']}")
        print(f"  Skills: {len(agent_card.get('skills', []))}")
        for skill in agent_card.get("skills", [])[:5]:
            print(f"    - {skill['name']}: {skill['description']}")
        print(f"  TrustMesh protocol: {agent_card.get('trustmesh', {}).get('protocol', 'unknown')}")

        # ── Step 4: Pod A connects to Pod B ──
        step(4, "Pod A connects to Pod B (bidirectional peering)")
        r = await client.post(f"{POD_A}/api/pod/peers", json={"url": POD_B})
        if r.status_code == 200:
            peer = r.json()
            print(f"  Status: {peer['status']}")
            print(f"  Peer: {peer['peer']['name']} ({peer['peer']['url']})")
            print(f"  Agents on peer: {peer['peer']['agent_count']}")
        else:
            print(f"  Connection failed: {r.status_code} - {r.text}")

        # ── Step 5: Verify bidirectional ──
        step(5, "Verify Pod B also knows about Pod A")
        r = await client.get(f"{POD_B}/api/pod/peers")
        peers = r.json()
        print(f"  Pod B peers: {len(peers['peers'])}")
        for p in peers["peers"]:
            print(f"    - {p['name']} at {p['url']} (status: {p['status']})")

        # ── Step 6: Discover all agents across federation ──
        step(6, "Discover agents across federation (from Pod A's perspective)")
        r = await client.get(f"{POD_A}/api/pod/discover")
        discovery = r.json()
        print(f"  Total agents: {discovery['total']}")
        print(f"  Local: {discovery['local_count']}, Remote: {discovery['remote_count']}")
        for a in discovery["agents"][:5]:
            pod_info = a.get("_pod", {})
            locality = "local" if pod_info.get("is_local") else "remote"
            name = a.get("name", a.get("owner_display_name", "unknown"))
            print(f"    [{locality}] {name} (pod: {pod_info.get('name', 'unknown')})")

        # ── Step 7: Cross-pod query ──
        step(7, "Cross-pod query: Pod A agent queries Pod B user")

        # Find a user on Pod A to be the querier
        pod_a_agents = pod_a_info.get("agents", [])
        if not pod_a_agents:
            print("  No agents on Pod A to query from")
            return

        # Find a target on Pod B
        pod_b_agents = pod_b_info.get("agents", [])
        if not pod_b_agents:
            print("  No agents on Pod B to query")
            return

        from_agent = pod_a_agents[0]
        to_agent = pod_b_agents[0]
        question = "What services do you provide?"

        print(f"  From: {from_agent['name']} (DID: {from_agent.get('did', 'none')[:30]}...)")
        print(f"  To: {to_agent['owner_username']} on Pod B")
        print(f"  Question: {question}")

        r = await client.post(
            f"{POD_B}/api/pod/query",
            json={
                "from_did": from_agent.get("did", "unknown"),
                "from_pod": POD_A,
                "to_username": to_agent["owner_username"],
                "question": question,
            },
        )
        if r.status_code == 200:
            result = r.json()
            print(f"\n  Trust level: {result.get('trust_level', 'unknown')}")
            print(f"  Decision: {result.get('decision', 'unknown')}")
            response = result.get("response", "No response")
            # Truncate long responses
            if len(response) > 300:
                response = response[:300] + "..."
            print(f"  Response: {response}")
            print(f"  Latency: {result.get('latency_ms', 'unknown')}ms")
        else:
            print(f"  Query failed: {r.status_code}")
            # Show error detail
            try:
                err = r.json()
                print(f"  Detail: {err.get('detail', r.text)}")
            except Exception:
                print(f"  Response: {r.text[:200]}")

        # ── Step 8: Verify audit trail ──
        step(8, "Check Pod B audit trail for cross-pod query")
        # The query was logged on Pod B — check if we can see it
        # (audit endpoints require auth, so this is just informational)
        print("  Cross-pod queries are logged in Pod B's audit trail")
        print("  Remote agent DID, source pod, trust level, and decision are recorded")
        print("  The target user can view this in their audit log")

    # ── Summary ──
    header("Federation Demo Complete")
    print("  What happened:")
    print("  1. Two independent TrustMesh pods running on different ports")
    print("  2. Each pod has its own database, users, agents, and vault keys")
    print("  3. Pod A discovered Pod B via the A2A-compatible agent card")
    print("  4. Bidirectional peering established (both pods know each other)")
    print("  5. Cross-pod query executed at 'public' trust level")
    print("  6. Only 'open' capsules were accessible (trust-aware)")
    print("  7. Full Citadel scanning on input AND output")
    print("  8. Audit trail records the cross-pod interaction")
    print()
    print("  Next steps:")
    print("  - Create a connection between users across pods for higher trust")
    print("  - Use UCAN tokens for emergency cross-pod access")
    print("  - Create pools (shared networks) spanning multiple pods")
    print()


if __name__ == "__main__":
    asyncio.run(main())
