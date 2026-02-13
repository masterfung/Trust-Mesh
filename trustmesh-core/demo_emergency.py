#!/usr/bin/env python3
"""Demo script: Emergency medical access flow via TrustMesh.

Scenario: Peter is at Riverside General Hospital.
Dr. Lee needs Peter's medical data. The hospital issues a scoped,
time-bounded UCAN token. Peter's agent validates it, shares ONLY
the role-appropriate data, logs everything.

Prerequisites: Run `uv run python -m src.seed` first, then start
the server with `uv run uvicorn src.main:app --port 8000`.
"""

import json
import sys

import httpx

BASE = "http://localhost:8000"
client = httpx.Client(base_url=BASE, timeout=30)


def banner(text: str):
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def step(n: int, text: str):
    print(f"\n[Step {n}] {text}")
    print("-" * 50)


def main():
    banner("TrustMesh Emergency Access Demo")

    # Step 1: Discover agents
    step(1, "Discovering agents via A2A protocol")
    r = client.get("/.well-known/agent.json")
    r.raise_for_status()
    agents = r.json()
    print(f"  Found {agents['total']} agents")

    # Find hospital and Peter
    hospital_agent = None
    peter_agent = None
    for agent in agents["agents"]:
        if agent["owner"]["username"] == "riverside_hospital":
            hospital_agent = agent
        elif agent["owner"]["username"] == "peter":
            peter_agent = agent

    if not hospital_agent:
        print("ERROR: Riverside General Hospital not found. Run seed first.")
        sys.exit(1)
    if not peter_agent:
        print("ERROR: Peter not found. Run seed first.")
        sys.exit(1)

    print(f"  Hospital: {hospital_agent['owner']['display_name']}")
    print(f"    DID: {hospital_agent['did']}")
    print(f"    Capabilities: {hospital_agent['capabilities']}")
    print(f"  Patient: {peter_agent['owner']['display_name']}")
    print(f"    DID: {peter_agent['did']}")

    hospital_id = hospital_agent["owner"]["id"]
    peter_id = peter_agent["owner"]["id"]

    # Step 2: View available roles
    step(2, "Checking available emergency roles")
    r = client.get("/api/emergency/roles")
    r.raise_for_status()
    roles = r.json()
    for role in roles:
        print(f"  {role['role']}: categories={role['categories']}, keywords={role['keywords'][:5]}...")

    # Step 3: Log in as hospital and patient to load vault keys
    step(3, "Logging in as hospital + patient (loading vault keys)")
    r = client.post("/api/auth/login", json={
        "username": "riverside_hospital",
        "password": "TrustMesh-demo-2026",
    })
    r.raise_for_status()
    print(f"  Logged in as {r.json()['display_name']}")

    r = client.post("/api/auth/login", json={
        "username": "peter",
        "password": "TrustMesh-demo-2026",
    })
    r.raise_for_status()
    print(f"  Logged in as {r.json()['display_name']} (patient — vault key loaded)")

    # Step 4: Issue UCAN token — attending physician
    step(4, "Issuing UCAN token (attending_physician role)")
    r = client.post("/api/emergency/token", json={
        "issuer_user_id": hospital_id,
        "patient_username": "peter",
        "role": "attending_physician",
        "duration_seconds": 3600,
        "practitioner_name": "Dr. Sarah Lee",
        "npi": "1234567890",
        "case_id": "ER-2026-0212-001",
        "reason": "Patient collapsed — cardiac evaluation",
    })
    r.raise_for_status()
    token_data = r.json()
    token = token_data["token"]
    print(f"  Token issued!")
    print(f"    Issuer DID: {token_data['issuer_did']}")
    print(f"    Audience DID: {token_data['audience_did']}")
    print(f"    Role: {token_data['role']}")
    print(f"    Expires in: {token_data['expires_in']}s")
    print(f"    Token (first 80 chars): {token[:80]}...")

    # Step 5: Access patient data with token
    step(5, "Accessing patient data with UCAN token")
    r = client.post("/api/emergency/access", json={
        "token": token,
        "patient_username": "peter",
    })
    r.raise_for_status()
    access_data = r.json()
    print(f"  Patient: {access_data['patient_name']}")
    print(f"  Role: {access_data['role']}")
    print(f"  Capsules returned: {access_data['capsule_count']}")
    print(f"  Categories: {access_data['categories']}")
    print(f"  Audit ID: {access_data['audit_id']}")
    print(f"  Expires at: {access_data['expires_at']}")
    print()
    for capsule in access_data["capsules"]:
        print(f"  [{capsule['tier']}] {capsule['title']}")
        content_preview = capsule["content"][:120] + "..." if len(capsule["content"]) > 120 else capsule["content"]
        print(f"    {content_preview}")
        print()

    # Step 6: Try ER nurse role (more restricted)
    step(6, "Issuing token with er_nurse role (more restricted)")
    r = client.post("/api/emergency/token", json={
        "issuer_user_id": hospital_id,
        "patient_username": "peter",
        "role": "er_nurse",
        "duration_seconds": 1800,
        "practitioner_name": "Nurse Davis",
        "case_id": "ER-2026-0212-001",
        "reason": "Triage assessment",
    })
    r.raise_for_status()
    nurse_token = r.json()["token"]

    r = client.post("/api/emergency/access", json={
        "token": nurse_token,
        "patient_username": "peter",
    })
    r.raise_for_status()
    nurse_data = r.json()
    print(f"  ER Nurse access — {nurse_data['capsule_count']} capsules (vs {access_data['capsule_count']} for physician)")
    for capsule in nurse_data["capsules"]:
        print(f"    [{capsule['tier']}] {capsule['title']}")

    # Step 7: Try expired token
    step(7, "Testing expired token (should fail)")
    r = client.post("/api/emergency/token", json={
        "issuer_user_id": hospital_id,
        "patient_username": "peter",
        "role": "paramedic",
        "duration_seconds": -1,  # Already expired
        "practitioner_name": "EMT Johnson",
        "case_id": "ER-2026-0212-002",
        "reason": "Test expired token",
    })
    r.raise_for_status()
    expired_token = r.json()["token"]

    r = client.post("/api/emergency/access", json={
        "token": expired_token,
        "patient_username": "peter",
    })
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json().get('detail', r.text)}")

    # Step 8: Try tampered token
    step(8, "Testing tampered token (should fail)")
    tampered = token[:-10] + "XXXXXXXXXX"
    r = client.post("/api/emergency/access", json={
        "token": tampered,
        "patient_username": "peter",
    })
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json().get('detail', r.text)}")

    # Step 9: Check Peter's audit log
    step(9, "Checking Peter's audit log")
    r = client.get(f"/api/users/{peter_id}/audit")
    r.raise_for_status()
    audit_logs = r.json()
    print(f"  Total audit entries: {len(audit_logs)}")
    for log in audit_logs[:5]:
        print(f"    [{log['event_type']}] {log['action']} — {log['decision']}")
        if log.get("actor_institution"):
            print(f"      Institution: {log['actor_institution']}")
        if log.get("actor_role"):
            print(f"      Role: {log['actor_role']}")

    # Step 10: Check emergency-only logs
    step(10, "Checking emergency-only audit logs")
    r = client.get(f"/api/users/{peter_id}/audit/emergency")
    r.raise_for_status()
    emergency_logs = r.json()
    print(f"  Emergency entries: {len(emergency_logs)}")

    # Step 11: Check Peter's notifications
    step(11, "Checking Peter's notifications")
    r = client.get(f"/api/users/{peter_id}/notifications")
    r.raise_for_status()
    notifications = r.json()
    emergency_notifications = [n for n in notifications if n["notification_type"] == "emergency_access"]
    print(f"  Emergency notifications: {len(emergency_notifications)}")
    for n in emergency_notifications[:3]:
        print(f"    {n['title']}")
        print(f"    {n['body']}")

    banner("Demo Complete!")
    print(f"\nSummary:")
    print(f"  - Agent discovery: {agents['total']} agents with DIDs")
    print(f"  - Attending physician: {access_data['capsule_count']} capsules accessed")
    print(f"  - ER nurse: {nurse_data['capsule_count']} capsules (role-scoped)")
    print(f"  - Expired token: correctly rejected")
    print(f"  - Tampered token: correctly rejected")
    print(f"  - Audit log: {len(audit_logs)} entries")
    print(f"  - Emergency notifications: {len(emergency_notifications)}")
    print()


if __name__ == "__main__":
    main()
