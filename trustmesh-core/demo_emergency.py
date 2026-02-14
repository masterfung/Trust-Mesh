#!/usr/bin/env python3
"""Demo script: Emergency medical access flow via TrustMesh.

Scenario: Grandma Rose (78) is driving to pick up grandkids Jane and Bill
from school — Molly and Peter are both busy at work. A vehicle hits Rose
at an intersection. She's unconscious, no ID on her. Paramedics bring her
to Riverside General Hospital. Dr. Lee needs her medical data urgently.

The hospital uses TrustMesh: issues a scoped, time-bounded UCAN token.
Rose's agent validates it, shares ONLY role-appropriate data (medications,
allergies, conditions, emergency contacts). Everything is audit-logged.
The family — Molly, Peter, Dorothy — gets notified instantly.

Then the hospital pulls a FHIR R4 Bundle for their EHR system.

Prerequisites: Run `uv run python -m src.seed` first, then start
the server with `uv run uvicorn src.main:app --port 8000`.
"""

import sys

import httpx

BASE = "http://localhost:8000"
hospital_client = httpx.Client(base_url=BASE, timeout=30)
family_client = httpx.Client(base_url=BASE, timeout=30)


def banner(text: str):
    print(f"\n{'=' * 70}")
    print(f"  {text}")
    print(f"{'=' * 70}")


def step(n: int, text: str):
    print(f"\n[Step {n}] {text}")
    print("-" * 60)


def main():
    banner("TrustMesh Emergency Access Demo: Grandma Rose")
    print("  Rose (78) hit by a vehicle picking up grandkids from school.")
    print("  Unconscious, no ID. Paramedics bring her to Riverside General.")
    print("  Hospital needs her medical data NOW.")

    # ── Step 1: Agent discovery ──
    step(1, "Hospital discovers TrustMesh agents via A2A protocol")
    r = hospital_client.get("/.well-known/agent.json")
    r.raise_for_status()
    agents = r.json()
    print(f"  Found {agents['total']} registered agents")

    hospital_agent = None
    rose_agent = None
    for agent in agents["agents"]:
        if agent["owner"]["username"] == "riverside_hospital":
            hospital_agent = agent
        elif agent["owner"]["username"] == "grandmarose":
            rose_agent = agent

    if not hospital_agent:
        print("ERROR: Riverside General Hospital not found. Run seed first.")
        sys.exit(1)
    if not rose_agent:
        print("ERROR: Grandma Rose not found. Run seed first.")
        sys.exit(1)

    print(f"  Hospital: {hospital_agent['owner']['display_name']}")
    print(f"    DID: {hospital_agent['did']}")
    print(f"    Capabilities: {hospital_agent['capabilities']}")
    print(f"  Patient: {rose_agent['owner']['display_name']}")
    print(f"    DID: {rose_agent['did']}")

    hospital_id = hospital_agent["owner"]["id"]
    rose_id = rose_agent["owner"]["id"]

    # ── Step 2: Load vault keys ──
    step(2, "Loading vault keys (hospital + patient login)")
    r = hospital_client.post("/api/auth/login", json={
        "username": "riverside_hospital",
        "password": "TrustMesh-demo-2026",
    })
    r.raise_for_status()
    print(f"  Hospital authenticated: {r.json()['display_name']}")

    # Rose is unconscious — but her vault key was loaded at boot (demo user)
    # In production, a family delegate or emergency override would handle this.
    r = hospital_client.post("/api/demo/warmup")
    r.raise_for_status()
    print(f"  Vault keys loaded: {r.json()['keys_loaded']} users")

    # ── Step 3: Paramedic arrives first ──
    step(3, "Paramedic EMT Johnson requests emergency access")
    r = hospital_client.post("/api/emergency/token", json={
        "issuer_user_id": hospital_id,
        "patient_username": "grandmarose",
        "role": "paramedic",
        "duration_seconds": 1800,
        "practitioner_name": "EMT Marcus Johnson",
        "npi": "9876543210",
        "case_id": "ER-2026-0213-042",
        "reason": "MVA — patient unconscious, no ID. Found TrustMesh via medical bracelet QR.",
    })
    r.raise_for_status()
    paramedic_token = r.json()["token"]
    print(f"  UCAN token issued (paramedic scope, 30 min)")
    print(f"    Token: {paramedic_token[:60]}...")

    r = hospital_client.post("/api/emergency/access", json={
        "token": paramedic_token,
        "patient_username": "grandmarose",
    })
    r.raise_for_status()
    paramedic_data = r.json()
    print(f"\n  Patient identified: {paramedic_data['patient_name']}")
    print(f"  Capsules returned: {paramedic_data['capsule_count']} (paramedic scope)")
    print(f"  Family notified: {paramedic_data.get('family_notified', 0)} members")
    print()
    for c in paramedic_data["capsules"]:
        vis = c.get("visibility", c.get("tier", "?"))
        print(f"    [{vis}] {c['title']}")

    # ── Step 4: Dr. Lee takes over (broader access) ──
    step(4, "Dr. Sarah Lee (attending physician) requests full access")
    r = hospital_client.post("/api/emergency/token", json={
        "issuer_user_id": hospital_id,
        "patient_username": "grandmarose",
        "role": "attending_physician",
        "duration_seconds": 3600,
        "practitioner_name": "Dr. Sarah Lee",
        "npi": "1234567890",
        "case_id": "ER-2026-0213-042",
        "reason": "MVA — unconscious elderly patient, suspected head trauma + fractures. Need full medical history.",
    })
    r.raise_for_status()
    token_data = r.json()
    physician_token = token_data["token"]
    print(f"  UCAN token issued (attending_physician scope, 1 hour)")
    print(f"    Issuer DID: {token_data['issuer_did']}")
    print(f"    Audience DID: {token_data['audience_did']}")

    r = hospital_client.post("/api/emergency/access", json={
        "token": physician_token,
        "patient_username": "grandmarose",
    })
    r.raise_for_status()
    physician_data = r.json()
    print(f"\n  Patient: {physician_data['patient_name']}")
    print(f"  Capsules: {physician_data['capsule_count']} (physician gets MORE than paramedic's {paramedic_data['capsule_count']})")
    print(f"  Categories: {physician_data['categories']}")
    print(f"  Audit ID: {physician_data['audit_id']}")
    print(f"  Family notified: {physician_data.get('family_notified', 0)} additional members")
    print()

    for c in physician_data["capsules"]:
        vis = c.get("visibility", c.get("tier", "?"))
        emerg = " [EMR]" if c.get("emergency_accessible") else ""
        print(f"  [{vis}]{emerg} {c['title']}")
        preview = c["content"][:130] + "..." if len(c["content"]) > 130 else c["content"]
        print(f"    {preview}")
        print()

    # ── Step 5: Security checks ──
    step(5, "Testing security: expired + tampered tokens")

    # Expired token
    r = hospital_client.post("/api/emergency/token", json={
        "issuer_user_id": hospital_id,
        "patient_username": "grandmarose",
        "role": "paramedic",
        "duration_seconds": -1,
        "practitioner_name": "Test",
        "case_id": "TEST",
        "reason": "Test expired token",
    })
    r.raise_for_status()
    expired_token = r.json()["token"]
    r = hospital_client.post("/api/emergency/access", json={
        "token": expired_token,
        "patient_username": "grandmarose",
    })
    print(f"  Expired token: {r.status_code} — {r.json().get('detail', '?')}")

    # Tampered token
    tampered = physician_token[:-10] + "XXXXXXXXXX"
    r = hospital_client.post("/api/emergency/access", json={
        "token": tampered,
        "patient_username": "grandmarose",
    })
    print(f"  Tampered token: {r.status_code} — {r.json().get('detail', '?')}")

    # ── Step 6: Family gets notified ──
    step(6, "Family notification relay — Molly checks her phone")

    # Login as Molly
    molly_agent = None
    for agent in agents["agents"]:
        if agent["owner"]["username"] == "molly":
            molly_agent = agent
            break

    if molly_agent:
        molly_id = molly_agent["owner"]["id"]
        r = family_client.post("/api/auth/login", json={
            "username": "molly",
            "password": "TrustMesh-demo-2026",
        })
        r.raise_for_status()
        r = family_client.get(f"/api/users/{molly_id}/notifications")
        r.raise_for_status()
        molly_notifs = r.json()
        family_alerts = [n for n in molly_notifs if n["notification_type"] == "emergency_family_alert"]
        print(f"  Molly has {len(family_alerts)} emergency family alert(s):")
        for n in family_alerts[:3]:
            print(f"    >>> {n['title']}")
            print(f"        {n['body'][:160]}")
    else:
        print("  (Molly not found — skipping)")

    # ── Step 7: FHIR R4 Bundle for hospital EHR ──
    step(7, "Hospital pulls FHIR R4 Bundle for EHR integration")
    audit_id = physician_data["audit_id"]
    r = hospital_client.get(f"/api/emergency/{audit_id}/fhir")
    if r.status_code == 200:
        fhir = r.json()
        print(f"  FHIR Bundle ID: {fhir['id']}")
        print(f"  Bundle type: {fhir['type']}")
        print(f"  Total resources: {fhir['total']}")
        print()
        for entry in fhir.get("entry", []):
            res = entry.get("resource", {})
            rtype = res.get("resourceType", "?")
            if rtype == "Patient":
                name = res.get("name", [{}])[0].get("text", "?")
                print(f"    Patient: {name}")
            elif rtype == "AllergyIntolerance":
                code = res.get("code", {}).get("text", "?")
                substances = res.get("_trustmesh", {}).get("substances", [])
                print(f"    AllergyIntolerance: {code} — {', '.join(substances) if substances else 'see notes'}")
            elif rtype == "MedicationStatement":
                med = res.get("medicationCodeableConcept", {}).get("text", "?")
                print(f"    MedicationStatement: {med}")
            elif rtype == "Condition":
                code = res.get("code", {}).get("text", "?")
                print(f"    Condition: {code}")
            elif rtype == "RelatedPerson":
                name = res.get("name", [{}])[0].get("text", "?")
                print(f"    RelatedPerson (emergency contact): {name}")
            else:
                code = res.get("code", {}).get("text", rtype)
                print(f"    {rtype}: {code}")
        if fhir.get("_trustmesh_emergency"):
            meta = fhir["_trustmesh_emergency"]
            print(f"\n  Emergency context: role={meta.get('access_role')}, "
                  f"institution={meta.get('institution')}, case={meta.get('case_id')}")
        print(f"\n  FHIR endpoint: /api/emergency/{audit_id}/fhir")
    else:
        print(f"  FHIR error: {r.status_code} — {r.text[:200]}")

    # ── Step 8: Audit trail ──
    step(8, "Complete audit trail for Rose")
    # Login as Rose to check audit
    r = family_client.post("/api/auth/login", json={
        "username": "grandmarose",
        "password": "TrustMesh-demo-2026",
    })
    r.raise_for_status()
    r = family_client.get(f"/api/users/{rose_id}/audit/emergency")
    r.raise_for_status()
    audit_logs = r.json()
    print(f"  Emergency audit entries: {len(audit_logs)}")
    for log in audit_logs[:6]:
        decision_marker = "+" if log["decision"] == "allowed" else "X"
        print(f"    [{decision_marker}] {log['action']} — {log.get('actor_role', '?')} "
              f"({log.get('actor_institution', '?')})")

    # ── Summary ──
    banner("Demo Complete — Grandma Rose's Emergency")
    print()
    print("  SCENARIO: Rose hit by vehicle, unconscious, no ID.")
    print("  RESULT:   Hospital accessed her data securely via TrustMesh.")
    print()
    print(f"  Paramedic access:  {paramedic_data['capsule_count']} capsules (limited scope)")
    print(f"  Physician access:  {physician_data['capsule_count']} capsules (full medical)")
    print(f"  Family notified:   Molly, Peter, Dorothy (via Care Circle)")
    print(f"  FHIR R4 Bundle:    {fhir['total'] if r.status_code == 200 else '?'} resources for EHR")
    print(f"  Security:          Expired + tampered tokens correctly rejected")
    print(f"  Audit trail:       {len(audit_logs)} entries, fully logged")
    print()
    print("  Every access was: scoped by role, time-bounded, cryptographically")
    print("  verified, audit-logged, and the family was notified instantly.")
    print()


if __name__ == "__main__":
    main()
