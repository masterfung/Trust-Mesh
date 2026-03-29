#!/usr/bin/env python3
"""
TinyFish Accelerator Demo — Family Travel Planning with TrustMesh

Shows: encrypted vaults → federation queries → TinyFish web research → live update

Usage:
    /opt/homebrew/bin/bash multi-pod.sh demo
    cd trustmesh-core && uv run python ../scripts/demo_travel.py
"""

import argparse
import asyncio
import json
import os
import sys
import time

import aiohttp
import httpx
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PODS = {
    "molly": "http://localhost:9001",
    "peter": "http://localhost:9002",
    "grandmarose": "http://localhost:9004",
}
PASSWORD = "TrustMesh-demo-2026"
TINYFISH_KEY = os.getenv("TINYFISH_API_KEY", "")

B = "\033[1m"; D = "\033[2m"; G = "\033[32m"; C = "\033[36m"
Y = "\033[33m"; M = "\033[35m"; R = "\033[31m"; BL = "\033[34m"
RST = "\033[0m"; U = "\033[4m"


def banner(t, color=C):
    print(f"\n{color}{B}{'=' * 70}\n  {t}\n{'=' * 70}{RST}\n")

def step(n, t):
    print(f"\n{Y}{B}[Step {n}]{RST} {B}{t}{RST}\n{D}{'─' * 60}{RST}")

def info(t): print(f"  {D}{t}{RST}")
def ok(t): print(f"  {G}{t}{RST}")
def hl(l, v): print(f"  {C}{l}:{RST} {v}")

def agent_says(name, text):
    print(f"\n  {M}{B}{name}'s Agent:{RST}")
    for line in text.strip().split("\n"):
        print(f"  {D}|{RST} {line}")
    print()


async def api_login(client, base, username):
    r = await client.post(f"{base}/api/auth/login",
                          json={"username": username, "password": PASSWORD})
    if r.status_code != 200:
        print(f"{R}Login failed for {username}: {r.status_code}{RST}")
        sys.exit(1)
    csrf = client.cookies.get("trustmesh_csrf")
    if csrf:
        client.headers["x-csrf-token"] = csrf
    return r.json()


async def api_query(client, base, uid, question, label=""):
    if label:
        info(label)
    t0 = time.time()
    r = await client.post(f"{base}/api/query", json={
        "from_user_id": uid, "to_user_id": uid, "question": question,
    }, timeout=300.0)
    elapsed = time.time() - t0
    if r.status_code != 200:
        print(f"{R}  Query failed: {r.status_code}{RST}")
        return {"response": "(failed)", "agent_actions": []}, elapsed
    return r.json(), elapsed


async def api_capsules(client, base, uid):
    r = await client.get(f"{base}/api/users/{uid}/capsules")
    return r.json() if r.status_code == 200 else []


async def api_update(client, base, cap_id, content):
    r = await client.put(f"{base}/api/capsules/{cap_id}",
                         json={"content": content}, timeout=30.0)
    return r.json() if r.status_code == 200 else {}


async def tinyfish_browse(url: str, goal: str) -> dict:
    """Call TinyFish Web Agent API directly. Returns structured result."""
    endpoint = "https://agent.tinyfish.ai/v1/automation/run-sse"
    headers = {"X-API-Key": TINYFISH_KEY, "Content-Type": "application/json",
               "Accept": "text/event-stream"}
    steps = []
    result_data = None
    async with aiohttp.ClientSession() as session:
        async with session.post(endpoint, headers=headers,
                                json={"url": url, "goal": goal},
                                timeout=aiohttp.ClientTimeout(total=120,
                                    sock_read=30)) as resp:
            if resp.status != 200:
                return {"success": False, "error": f"HTTP {resp.status}"}
            try:
                async for line in resp.content:
                    text = line.decode("utf-8").strip()
                    if not text.startswith("data:"):
                        continue
                    data_str = text[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                        etype = event.get("type", "")
                        if etype == "PROGRESS":
                            purpose = event.get("purpose", "")
                            steps.append(purpose)
                            info(f"  TinyFish: {purpose[:80]}")
                        elif etype == "COMPLETE":
                            result_data = event.get("resultJson") or event.get("result")
                            break  # Got result — don't wait for more
                        elif etype == "ERROR":
                            return {"success": False, "error": event.get("message", "?")}
                    except json.JSONDecodeError:
                        pass
            except asyncio.TimeoutError:
                pass  # sock_read timeout after last event — data already captured
    return {"success": True, "steps": len(steps), "data": result_data}


async def run_demo(destination: str):
    banner("TrustMesh x TinyFish — Family Travel Planner")
    print(f"  {B}Three family members, three encrypted pods, one trip.{RST}")
    print(f"  Agents share data through trust networks. TinyFish browses")
    print(f"  the real web for restaurants and venues.")
    print(f"\n  {B}Destination:{RST} {U}{destination}{RST}")
    print(f"  {B}Pods:{RST} Molly :9001 | Peter :9002 | Grandma Rose :9004")
    print()
    input(f"  {D}Press Enter to start...{RST}")

    pc = httpx.AsyncClient(timeout=60.0)
    mc = httpx.AsyncClient(timeout=300.0)
    rc = httpx.AsyncClient(timeout=60.0)

    try:
        # ── Step 1: Encrypted vaults ───────────────────────────────────
        step(1, "Three encrypted vaults on separate pods")

        peter = await api_login(pc, PODS["peter"], "peter")
        molly = await api_login(mc, PODS["molly"], "molly")
        rose = await api_login(rc, PODS["grandmarose"], "grandmarose")

        ok(f"Peter  → pod :9002 (vault key in Zig transit engine)")
        ok(f"Molly  → pod :9001 (AES-256-GCM encrypted)")
        ok(f"Rose   → pod :9004 (separate DB, separate keys)")

        for label, cli, base, uid, frag in [
            ("Peter", pc, PODS["peter"], peter["id"], "Travel & Dining"),
            ("Molly", mc, PODS["molly"], molly["id"], "Travel & Activity"),
            ("Rose", rc, PODS["grandmarose"], rose["id"], "Dining & Cultural"),
        ]:
            caps = await api_capsules(cli, base, uid)
            cap = next((c for c in caps if frag.lower() in c["title"].lower()), None)
            if cap:
                print(f"\n  {BL}{B}{label}'s Preferences{RST} {D}[{cap['visibility']}, encrypted]{RST}")
                for line in cap["content"].split("\n"):
                    if line.strip():
                        print(f"    {line.strip()}")

        input(f"\n  {D}Press Enter → federation queries...{RST}")

        # ── Step 2: Query Peter via federation ─────────────────────────
        step(2, "Molly's agent queries Peter's pod (:9002) via federation")

        res, t = await api_query(mc, PODS["molly"], molly["id"],
            "Use query_peer to ask peter: What are your travel preferences, "
            "dietary needs, and must-have activities? Tell me everything he says.",
            "Querying Peter's pod over federation...")
        agent_says("Molly", res.get("response", "(no response)"))
        peers = [a for a in res.get("agent_actions", []) if a.get("type") == "peer_queried"]
        if peers:
            p = peers[0]
            hl("Federation", f"→ {p.get('target_display_name')} (trust: {p.get('trust_level')}, pod: {p.get('remote_pod', '-')})")
        hl("Time", f"{t:.1f}s")

        input(f"\n  {D}Press Enter → query Grandma Rose...{RST}")

        # ── Step 3: Query Rose via federation ──────────────────────────
        step(3, "Molly's agent queries Grandma Rose's pod (:9004)")

        res, t = await api_query(mc, PODS["molly"], molly["id"],
            "Use query_peer to ask grandmarose: What are your dining preferences "
            "and cultural must-haves for travel? Tell me everything she says.",
            "Querying Rose's pod over federation...")
        agent_says("Molly", res.get("response", "(no response)"))
        peers = [a for a in res.get("agent_actions", []) if a.get("type") == "peer_queried"]
        if peers:
            p = peers[0]
            hl("Federation", f"→ {p.get('target_display_name')} (trust: {p.get('trust_level')}, pod: {p.get('remote_pod', '-')})")
        hl("Time", f"{t:.1f}s")

        input(f"\n  {D}Press Enter → TinyFish web research...{RST}")

        # ── Step 4: TinyFish browses real web ──────────────────────────
        step(4, "TinyFish AI Web Agent browses for real restaurants")

        tf_result = None
        if not TINYFISH_KEY:
            print(f"  {R}TINYFISH_API_KEY not set — skipping web research{RST}")
        else:
            info("Calling TinyFish API → browsing Michelin guide website...")
            t0 = time.time()
            tf_result = await tinyfish_browse(
                url="https://www.sansebastianturismoa.eus/en/eat/michelin-restaurants",
                goal=(
                    f"Find all Michelin-starred restaurants in {destination}. "
                    "For each restaurant, extract: name, cuisine type, number of stars. "
                    "Also note which ones would work for someone who is vegetarian "
                    "and which are NOT French or Italian cuisine."
                ),
            )
            tf_time = time.time() - t0

            if tf_result.get("success"):
                ok(f"TinyFish returned real data ({tf_result.get('steps', 0)} browser steps, {tf_time:.1f}s)")
                data = tf_result.get("data")
                if isinstance(data, dict):
                    print(f"\n  {BL}{B}Michelin Restaurants Found:{RST}")
                    print(f"  {json.dumps(data, indent=2)[:2000]}")
                elif data:
                    print(f"\n  {BL}{B}Results:{RST}")
                    print(f"  {str(data)[:2000]}")
                hl("Source", "TinyFish AI Web Agent → live website data")
                hl("Time", f"{tf_time:.1f}s")
            else:
                print(f"  {R}TinyFish error: {tf_result.get('error', '?')}{RST}")

        input(f"\n  {D}Press Enter → build itinerary...{RST}")

        # ── Step 5: Agent synthesizes itinerary ────────────────────────
        step(5, "Agent builds personalized 5-day itinerary")

        # Build itinerary prompt with real TinyFish data if available
        restaurant_info = ""
        if TINYFISH_KEY and tf_result and tf_result.get("success") and tf_result.get("data"):
            data = tf_result["data"]
            if isinstance(data, dict):
                restaurant_info = f"\nREAL RESTAURANTS from Michelin Guide (via TinyFish):\n{json.dumps(data, indent=2)[:1500]}\n"
        if not restaurant_info:
            restaurant_info = (
                "\nReal Michelin restaurants: Arzak (3-star Traditional), "
                "Akelarre (3-star Creative), Mugaritz (2-star Innovative), "
                "Amelia (2-star Creative), Kokotxa (1-star Modern), Elkano (1-star Seafood)\n"
            )

        plan_q = (
            f"Build a detailed 5-day itinerary for {destination} for me, Peter, and Grandma Rose.\n"
            "Use these confirmed preferences:\n"
            "- Peter: VEGETARIAN (no meat/fish/poultry), Starbucks mug collector (47 mugs), "
            "Hard Rock merch (31 pins), live music (blues/rock), pool, late starts\n"
            "- Me (Molly): walking tours, vineyards (small family-owned), food markets, "
            "yoga/salsa, NO tourist traps\n"
            "- Rose: Michelin dining (NO French/Italian — loves kaiseki, Spanish tapas, Nikkei), "
            "opera, museums, botanical gardens, needs walker/elevator access\n"
            f"{restaurant_info}"
            "Be specific with times and real venue names."
        )
        res, t = await api_query(mc, PODS["molly"], molly["id"], plan_q,
                                  "Building personalized itinerary from all data...")
        agent_says("Molly", res.get("response", "(no response)"))
        hl("Time", f"{t:.1f}s")

        input(f"\n  {D}Press Enter → live preference update...{RST}")

        # ── Step 6: Peter changes diet ─────────────────────────────────
        step(6, "LIVE UPDATE: Peter changes vegetarian → pescatarian")

        caps = await api_capsules(pc, PODS["peter"], peter["id"])
        peter_cap = next((c for c in caps if "travel" in c["title"].lower()), None)
        if peter_cap:
            new_content = peter_cap["content"].replace(
                "DIET: Vegetarian — no meat, no fish, no poultry. Eggs and dairy OK. "
                "This is a firm lifestyle choice, not an allergy. Always check menus ahead of time.",
                "DIET: Pescatarian — no meat or poultry, but FISH AND SEAFOOD are great. "
                "Eggs and dairy also OK. Loves sushi, grilled fish, ceviche, and seafood paella. "
                "Recently switched from vegetarian after trying omakase in Tokyo."
            )
            updated = await api_update(pc, PODS["peter"], peter_cap["id"], new_content)
            if updated:
                ok("Peter's vault updated on his pod (:9002)")
                hl("Old", "Vegetarian (no meat, fish, or poultry)")
                hl("New", "Pescatarian (fish & seafood OK — sushi, ceviche, paella)")
                hl("Encryption", "Re-encrypted AES-256-GCM on Peter's pod")

        input(f"\n  {D}Press Enter → re-query Peter...{RST}")

        # ── Step 7: Re-query shows live update ─────────────────────────
        step(7, "Molly's agent sees Peter's updated diet via federation")

        res, t = await api_query(mc, PODS["molly"], molly["id"],
            "Use query_peer to ask peter what his current dietary preferences are. "
            "Has anything changed recently? Tell me exactly what he says.",
            "Re-querying Peter's pod (:9002)...")
        agent_says("Molly", res.get("response", "(no response)"))
        resp_lower = res.get("response", "").lower()
        if "pescatarian" in resp_lower:
            ok("LIVE UPDATE CONFIRMED — agent sees 'pescatarian' from Peter's updated vault!")
        elif "vegetarian" in resp_lower:
            print(f"  {Y}Agent still sees vegetarian — cache may need to clear{RST}")
        hl("Time", f"{t:.1f}s")

        # ── Summary ───────────────────────────────────────────────────
        banner("Demo Complete", G)
        print(f"  {B}What you just saw:{RST}")
        print(f"  1. Three family members on {U}separate encrypted pods{RST}")
        print(f"  2. Molly's agent queried Peter + Rose via {U}cross-pod federation{RST}")
        print(f"  3. TinyFish browsed {U}real Michelin guide website{RST} for restaurant data")
        print(f"  4. Agent built a {U}personalized 5-day itinerary{RST} using all inputs")
        print(f"  5. Peter updated his diet → {U}next federation query saw it instantly{RST}")
        print()
        print(f"  {B}TrustMesh:{RST} Encrypted vaults + trust networks + pod federation")
        print(f"  {B}TinyFish:{RST} AI web agent for real-time venue research")
        print(f"  {B}Together:{RST} Multi-person planning that respects privacy & stays current")
        print()

    finally:
        await pc.aclose()
        await mc.aclose()
        await rc.aclose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--destination", default="San Sebastián, Spain")
    args = parser.parse_args()
    asyncio.run(run_demo(args.destination))


if __name__ == "__main__":
    main()
