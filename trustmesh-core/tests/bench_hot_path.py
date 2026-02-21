"""
Hot-path performance benchmark — measures p50/p95/p99 latencies for
the routes that fire on every page load and polling cycle.

Usage:
  # Ensure backend is running on :8000
  cd trustmesh-core && uv run python tests/bench_hot_path.py

  # Or with Zig HTTP proxy:
  TRUSTMESH_ZIG_HTTP=1 ./dev.sh start
  cd trustmesh-core && uv run python tests/bench_hot_path.py

Environment:
  BENCH_BACKEND_URL  (default: http://localhost:8000)
  BENCH_ITERATIONS   (default: 200)
"""

import os
import statistics
import sys
import time

import httpx

BASE = os.getenv("BENCH_BACKEND_URL", "http://localhost:8000")
ITERATIONS = int(os.getenv("BENCH_ITERATIONS", "200"))
TIMEOUT = 10.0


def _percentile(data: list[float], p: float) -> float:
    """Return the p-th percentile of a sorted list."""
    if not data:
        return 0.0
    k = (len(data) - 1) * (p / 100)
    f = int(k)
    c = f + 1
    if c >= len(data):
        return data[f]
    return data[f] + (k - f) * (data[c] - data[f])


def bench(client: httpx.Client, method: str, path: str, *, json_body=None) -> list[float]:
    """Run ITERATIONS requests and return sorted latencies in ms."""
    url = f"{BASE}{path}"
    latencies = []
    errors = 0
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        try:
            if method == "GET":
                resp = client.get(url, timeout=TIMEOUT)
            elif method == "POST":
                resp = client.post(url, json=json_body or {}, timeout=TIMEOUT)
            elif method == "PUT":
                resp = client.put(url, json=json_body or {}, timeout=TIMEOUT)
            else:
                raise ValueError(f"Unknown method: {method}")
            elapsed_ms = (time.perf_counter() - start) * 1000
            if resp.status_code < 500:
                latencies.append(elapsed_ms)
            else:
                errors += 1
        except (httpx.TimeoutException, httpx.ConnectError):
            errors += 1
    latencies.sort()
    if errors > 0:
        print(f"    ({errors} errors)")
    return latencies


def report(name: str, latencies: list[float]):
    """Print percentile summary."""
    if not latencies:
        print(f"  {name:40s}  NO DATA")
        return
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    avg = statistics.mean(latencies)
    print(f"  {name:40s}  p50={p50:6.1f}ms  p95={p95:6.1f}ms  p99={p99:6.1f}ms  avg={avg:6.1f}ms  n={len(latencies)}")


def main():
    print(f"\nTrustMesh Hot-Path Benchmark")
    print(f"  Backend:    {BASE}")
    print(f"  Iterations: {ITERATIONS}")
    print()

    # Check backend is up
    try:
        resp = httpx.get(f"{BASE}/health/full", timeout=5)
        health = resp.json()
        zig_http = health.get("zig_http", False)
        print(f"  Mode: {'Zig HTTP proxy' if zig_http else 'Python-only'}")
    except Exception as e:
        print(f"  ERROR: Backend not reachable at {BASE}: {e}")
        sys.exit(1)

    # Login to get a session cookie
    client = httpx.Client()
    resp = client.post(f"{BASE}/api/auth/login", json={
        "username": "molly",
        "password": "TrustMesh2024!",
    })
    if resp.status_code != 200:
        print(f"  ERROR: Login failed ({resp.status_code})")
        sys.exit(1)

    # Get user ID
    me = client.get(f"{BASE}/api/auth/me").json()
    user_id = me.get("user_id") or me.get("id")
    if not user_id:
        print(f"  ERROR: Could not get user ID from /api/auth/me")
        sys.exit(1)
    print(f"  User:       {me.get('username', '?')} ({user_id})")

    # Warmup
    print("\n  Warming up (10 requests each)...")
    for _ in range(10):
        client.get(f"{BASE}/api/users/{user_id}", timeout=TIMEOUT)
        client.get(f"{BASE}/api/users/{user_id}/notifications", timeout=TIMEOUT)
        client.get(f"{BASE}/api/users/{user_id}/connections", timeout=TIMEOUT)
        client.get(f"{BASE}/api/users/{user_id}/capsules", timeout=TIMEOUT)

    print(f"\n  Running {ITERATIONS} iterations per endpoint...\n")

    results = {}

    # Health check (baseline)
    results["GET /health/full"] = bench(client, "GET", "/health/full")

    # Auth (session lookup)
    results["GET /api/auth/me"] = bench(client, "GET", "/api/auth/me")

    # User profile (page load)
    results[f"GET /api/users/{{id}}"] = bench(client, "GET", f"/api/users/{user_id}")

    # Connections (dashboard sidebar)
    results[f"GET /api/users/{{id}}/connections"] = bench(
        client, "GET", f"/api/users/{user_id}/connections"
    )

    # Notifications (polling every 3-5s)
    results[f"GET /api/users/{{id}}/notifications"] = bench(
        client, "GET", f"/api/users/{user_id}/notifications"
    )

    # Notification unread count (badge)
    results[f"GET /api/users/{{id}}/notifications/unread-count"] = bench(
        client, "GET", f"/api/users/{user_id}/notifications/unread-count"
    )

    # Capsules (vault page)
    results[f"GET /api/users/{{id}}/capsules"] = bench(
        client, "GET", f"/api/users/{user_id}/capsules"
    )

    # Audit log
    results[f"GET /api/users/{{id}}/audit"] = bench(
        client, "GET", f"/api/users/{user_id}/audit"
    )

    # Timeline state
    results["GET /api/timeline/state"] = bench(client, "GET", "/api/timeline/state")

    # Timeline entries
    results["GET /api/timeline/entries"] = bench(client, "GET", "/api/timeline/entries")

    # Memory health (Zig-native)
    results["GET /api/memory/health"] = bench(client, "GET", "/api/memory/health")

    # Print results
    print("=" * 90)
    print(f"  {'Endpoint':40s}  {'p50':>8s}  {'p95':>8s}  {'p99':>8s}  {'avg':>8s}  {'n':>5s}")
    print("-" * 90)
    for name, latencies in results.items():
        report(name, latencies)
    print("=" * 90)

    # Summary
    all_latencies = [l for ls in results.values() for l in ls]
    if all_latencies:
        total_p50 = _percentile(sorted(all_latencies), 50)
        total_p95 = _percentile(sorted(all_latencies), 95)
        print(f"\n  Overall: p50={total_p50:.1f}ms  p95={total_p95:.1f}ms  ({len(all_latencies)} total requests)")

    client.close()
    print()


if __name__ == "__main__":
    main()
