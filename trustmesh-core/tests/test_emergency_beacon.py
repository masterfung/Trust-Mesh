"""Tests for self-issued UCAN emergency beacon endpoints.

POST /api/users/{id}/emergency/beacon  — patient generates QR tokens for 3 roles
GET  /api/emergency/qr                 — first-responder scans QR, gets scoped records

Also covers unit tests for:
  - capsule_matches_scope() per beacon role
  - token_hash() consistency
  - create_ucan_token() with beacon audience (did:emergency:any)
"""

import base64
import json
import time
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import init_db, drop_db, get_db
from src.models import AuditLog, KnowledgeCapsule, Agent
from src.rate_limit import reset_rate_limits
from src.ucan import (
    ROLE_SCOPES,
    capsule_matches_scope,
    create_ucan_token,
    token_hash,
)
from src.crypto import generate_ed25519_keypair


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    sessions.clear()
    _login_attempts.clear()
    reset_rate_limits()
    await drop_db()
    await init_db()
    yield
    await drop_db()


@pytest_asyncio.fixture
async def client():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


PATIENT = {
    "username": "grandmarose",
    "display_name": "Rose Johnson",
    "bio": "Retired nurse. Blood type A+.",
    "password": "EmerTest1Secure!",
}

FAMILY = {
    "username": "mollyjohnson",
    "display_name": "Molly Johnson",
    "bio": "Daughter",
    "password": "FamilyTest1Secure!",
}


async def _create_and_login(client: AsyncClient, user_data: dict) -> str:
    """Create user via POST /api/users (which also logs in) and return user_id."""
    resp = await client.post("/api/users", json=user_data)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _seed_health_capsule(
    user_id: str,
    title: str,
    content: str,
    category: str = "health",
) -> str:
    """Insert an emergency-accessible capsule directly via DB."""
    from src import transit_bridge

    async for db in get_db():
        try:
            encrypted = transit_bridge.encrypt(user_id, content.encode())
        except Exception:
            encrypted = content.encode()

        cap_id = str(uuid.uuid4())
        capsule = KnowledgeCapsule(
            id=cap_id,
            owner_id=user_id,
            title=title,
            content_encrypted=encrypted,
            category=category,
            capsule_type="note",
            emergency_accessible=True,
            visibility="private",
        )
        db.add(capsule)
        await db.commit()
        return cap_id
    return ""


# ── Unit: capsule_matches_scope ───────────────────────────────────────────────


class TestCapsuleMatchesScope:
    def test_paramedic_matches_blood_type(self):
        # keyword is "blood_type" (underscore) — must appear exactly
        cap = {"title": "blood_type info", "content": "A positive", "category": ""}
        assert capsule_matches_scope(cap, "paramedic")

    def test_paramedic_matches_allergy_keyword(self):
        # keyword is "allergy" (singular) — must appear with word boundary
        cap = {"title": "Known allergy", "content": "Penicillin allergy on file", "category": ""}
        assert capsule_matches_scope(cap, "paramedic")

    def test_paramedic_matches_dnr(self):
        cap = {"title": "DNR status", "content": "Do not resuscitate on file", "category": ""}
        assert capsule_matches_scope(cap, "paramedic")

    def test_paramedic_does_not_match_medication_list(self):
        """Paramedic scope excludes detailed medication history."""
        cap = {"title": "Medication list", "content": "Atorvastatin 20mg daily", "category": ""}
        assert not capsule_matches_scope(cap, "paramedic")

    def test_paramedic_matches_health_category(self):
        """Any capsule in the 'health' category matches all roles."""
        cap = {"title": "Misc note", "content": "Some data", "category": "health"}
        assert capsule_matches_scope(cap, "paramedic")

    def test_er_nurse_includes_weight_height(self):
        cap = {"title": "Vitals", "content": "Weight 65kg, Height 165cm", "category": ""}
        assert capsule_matches_scope(cap, "er_nurse")

    def test_er_nurse_does_not_match_medication(self):
        cap = {"title": "Prescriptions", "content": "Atorvastatin 20mg", "category": ""}
        assert not capsule_matches_scope(cap, "er_nurse")

    def test_attending_physician_matches_medication(self):
        # keyword is "medication" (singular) — "Medication list" title has word boundary
        cap = {"title": "Medication list", "content": "Atorvastatin, Metformin", "category": ""}
        assert capsule_matches_scope(cap, "attending_physician")

    def test_attending_physician_matches_surgery(self):
        # keyword is "surgery" (not "surgical")
        cap = {"title": "Surgery history", "content": "Appendectomy 2010", "category": ""}
        assert capsule_matches_scope(cap, "attending_physician")

    def test_attending_physician_matches_insurance(self):
        cap = {"title": "Insurance info", "content": "Blue Cross policy", "category": ""}
        assert capsule_matches_scope(cap, "attending_physician")

    def test_unknown_role_returns_false(self):
        cap = {"title": "Anything", "content": "anything", "category": "health"}
        assert not capsule_matches_scope(cap, "ghost_role")

    def test_word_boundary_no_false_positives(self):
        """'doctored' should not match 'doctor' keyword."""
        cap = {"title": "Evidence was doctored", "content": "Fraud", "category": ""}
        # 'doctored' contains 'doctor' but at a word boundary it shouldn't match
        # The regex uses \bdoctor\b which won't match "doctored"
        result = capsule_matches_scope(cap, "attending_physician")
        assert not result, "'doctored' should not match 'doctor' keyword"


# ── Unit: token_hash ──────────────────────────────────────────────────────────


def test_token_hash_deterministic():
    """Same token always produces the same SHA-256 hex hash."""
    tok = "abc.def"
    assert token_hash(tok) == token_hash(tok)
    assert len(token_hash(tok)) == 64  # SHA-256 hex


def test_token_hash_distinct():
    """Different tokens produce different hashes."""
    assert token_hash("aaa.bbb") != token_hash("aaa.ccc")


# ── Unit: self-issued beacon token format ────────────────────────────────────


def test_create_beacon_token_format():
    """create_ucan_token with aud=did:emergency:any produces a valid two-part token."""
    private_key, public_key = generate_ed25519_keypair()
    token = create_ucan_token(
        issuer_did="did:key:z6MkPatient",
        issuer_private_key=private_key,
        audience_did="did:emergency:any",
        role="paramedic",
        duration_seconds=1800,
        facts={"emergency_beacon": True, "issued_by": "Test Patient"},
    )
    parts = token.split(".")
    assert len(parts) == 2, "Token must be payload.signature"


def test_create_beacon_token_payload_fields():
    """Beacon token payload contains expected fields."""
    private_key, _ = generate_ed25519_keypair()
    token = create_ucan_token(
        issuer_did="did:key:z6MkTest",
        issuer_private_key=private_key,
        audience_did="did:emergency:any",
        role="er_nurse",
        duration_seconds=1800,
        facts={"emergency_beacon": True},
    )
    payload_b64 = token.split(".")[0]
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    payload = json.loads(base64.urlsafe_b64decode(payload_b64))

    assert payload["aud"] == "did:emergency:any"
    assert payload["iss"] == "did:key:z6MkTest"
    assert payload["att"]["role"] == "er_nurse"
    assert payload["fct"]["emergency_beacon"] is True
    assert payload["exp"] > int(time.time())


def test_beacon_tokens_for_all_roles():
    """A unique token is created for each role."""
    private_key, _ = generate_ed25519_keypair()
    roles = ["paramedic", "er_nurse", "attending_physician"]
    tokens = {
        role: create_ucan_token(
            issuer_did="did:key:z6MkRose",
            issuer_private_key=private_key,
            audience_did="did:emergency:any",
            role=role,
            duration_seconds=1800,
            facts={"emergency_beacon": True},
        )
        for role in roles
    }
    # Verify all tokens are distinct (different role in payload)
    assert len(set(tokens.values())) == 3


# ── HTTP: POST /api/users/{id}/emergency/beacon ───────────────────────────────


@pytest.mark.asyncio
async def test_beacon_requires_auth(client):
    """Beacon endpoint returns 401 without a session."""
    resp = await client.post("/api/users/nonexistent/emergency/beacon")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_beacon_requires_own_user(client):
    """Authenticated user cannot generate a beacon for a different user."""
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c2:
        other_id = await _create_and_login(c2, FAMILY)

    # First client is logged in as PATIENT, tries to access FAMILY's beacon
    patient_id = await _create_and_login(client, PATIENT)
    resp = await client.post(f"/api/users/{other_id}/emergency/beacon")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_beacon_returns_tokens_for_all_roles(client):
    """Successful beacon returns tokens + QR URLs for all 3 roles."""
    patient_id = await _create_and_login(client, PATIENT)

    resp = await client.post(f"/api/users/{patient_id}/emergency/beacon")
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert "tokens" in data
    assert "qr_urls" in data
    assert set(data["tokens"].keys()) == {"paramedic", "er_nurse", "attending_physician"}
    assert set(data["qr_urls"].keys()) == {"paramedic", "er_nurse", "attending_physician"}
    assert data["expires_in"] == 1800
    assert data["patient_name"] == "Rose Johnson"


@pytest.mark.asyncio
async def test_beacon_tokens_are_valid_ucan(client):
    """Beacon tokens can be decoded and have the expected beacon payload."""
    patient_id = await _create_and_login(client, PATIENT)

    resp = await client.post(f"/api/users/{patient_id}/emergency/beacon")
    assert resp.status_code == 200

    data = resp.json()
    for role, token in data["tokens"].items():
        parts = token.split(".")
        assert len(parts) == 2, f"Token for {role} has wrong format"

        payload_b64 = parts[0]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        assert payload["aud"] == "did:emergency:any", f"{role}: aud must be sentinel"
        assert payload["att"]["role"] == role, f"{role}: att.role mismatch"
        assert payload["fct"].get("emergency_beacon") is True
        assert payload["exp"] > int(time.time())


@pytest.mark.asyncio
async def test_beacon_creates_audit_log(client):
    """Beacon generation writes an emergency audit log entry."""
    patient_id = await _create_and_login(client, PATIENT)

    resp = await client.post(f"/api/users/{patient_id}/emergency/beacon")
    assert resp.status_code == 200
    audit_id = resp.json()["audit_id"]

    async for db in get_db():
        entry = await db.get(AuditLog, audit_id)
        assert entry is not None
        assert entry.event_type == "emergency"
        assert entry.action == "emergency_beacon_generated"
        assert entry.actor_user_id == patient_id
        break


@pytest.mark.asyncio
async def test_beacon_qr_urls_contain_token_and_patient(client):
    """QR URLs include the token and patient username."""
    patient_id = await _create_and_login(client, PATIENT)

    resp = await client.post(f"/api/users/{patient_id}/emergency/beacon")
    assert resp.status_code == 200

    data = resp.json()
    for role, url in data["qr_urls"].items():
        assert "?t=" in url, f"{role} QR URL missing token param"
        assert "p=grandmarose" in url, f"{role} QR URL missing patient param"


# ── HTTP: GET /api/emergency/qr ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_qr_scan_requires_t_and_p(client):
    """GET /api/emergency/qr without params returns error."""
    resp = await client.get("/api/emergency/qr")
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_qr_scan_expired_token(client):
    """Expired beacon token returns 403."""
    patient_id = await _create_and_login(client, PATIENT)

    # Get a valid token to find patient's DID, then create an expired one
    beacon_resp = await client.post(f"/api/users/{patient_id}/emergency/beacon")
    assert beacon_resp.status_code == 200

    # Fetch patient's private key indirectly: create an expired token using direct key access
    from src import transit_bridge

    async for db in get_db():
        agent_result = await db.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(Agent).where(Agent.owner_id == patient_id)
        )
        agent = agent_result.scalar_one_or_none()
        assert agent is not None
        private_key = transit_bridge.decrypt(patient_id, agent.encrypted_private_key)
        expired_token = create_ucan_token(
            issuer_did=agent.did,
            issuer_private_key=private_key,
            audience_did="did:emergency:any",
            role="paramedic",
            duration_seconds=-1,  # already expired
            facts={"emergency_beacon": True},
        )
        break

    resp = await client.get("/api/emergency/qr", params={"t": expired_token, "p": "grandmarose"})
    assert resp.status_code == 403
    assert "expired" in resp.text.lower()


@pytest.mark.asyncio
async def test_qr_scan_unknown_patient(client):
    """QR scan with unknown patient username returns 403."""
    patient_id = await _create_and_login(client, PATIENT)

    beacon_resp = await client.post(f"/api/users/{patient_id}/emergency/beacon")
    assert beacon_resp.status_code == 200
    token = beacon_resp.json()["tokens"]["paramedic"]

    resp = await client.get("/api/emergency/qr", params={"t": token, "p": "nobody_exists"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_qr_scan_invalid_signature(client):
    """Token with tampered payload returns 403 signature error."""
    patient_id = await _create_and_login(client, PATIENT)

    beacon_resp = await client.post(f"/api/users/{patient_id}/emergency/beacon")
    assert beacon_resp.status_code == 200
    good_token = beacon_resp.json()["tokens"]["paramedic"]

    # Tamper with the payload while keeping the original signature
    parts = good_token.split(".")
    payload_b64 = parts[0]
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    payload["att"]["role"] = "attending_physician"  # promote role without re-signing
    tampered_payload = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).rstrip(b"=").decode()
    tampered_token = f"{tampered_payload}.{parts[1]}"

    resp = await client.get("/api/emergency/qr", params={"t": tampered_token, "p": "grandmarose"})
    assert resp.status_code == 403
    assert "signature" in resp.text.lower() or "issuer" in resp.text.lower()


@pytest.mark.asyncio
async def test_qr_scan_returns_scoped_capsules(client):
    """Valid beacon scan returns capsules filtered by role scope.

    Uses keyword-only matching (no 'health' category) so that role scope actually
    differentiates between paramedic and attending_physician access.
    """
    patient_id = await _create_and_login(client, PATIENT)

    # blood_type keyword (exact, with underscore) — paramedic can see
    await _seed_health_capsule(patient_id, "blood_type record", "A positive", category="")
    # medication keyword — attending_physician can see, paramedic cannot
    await _seed_health_capsule(patient_id, "Medication list", "Atorvastatin 20mg", category="")

    beacon_resp = await client.post(f"/api/users/{patient_id}/emergency/beacon")
    assert beacon_resp.status_code == 200
    paramedic_token = beacon_resp.json()["tokens"]["paramedic"]
    physician_token = beacon_resp.json()["tokens"]["attending_physician"]

    # Paramedic sees blood_type record but NOT medication
    resp_paramedic = await client.get(
        "/api/emergency/qr", params={"t": paramedic_token, "p": "grandmarose"}
    )
    assert resp_paramedic.status_code == 200, resp_paramedic.text
    para_data = resp_paramedic.json()
    capsule_titles_para = [c["title"] for c in para_data["capsules"]]
    assert "blood_type record" in capsule_titles_para
    assert "Medication list" not in capsule_titles_para

    # Attending physician sees both
    resp_physician = await client.get(
        "/api/emergency/qr", params={"t": physician_token, "p": "grandmarose"}
    )
    assert resp_physician.status_code == 200, resp_physician.text
    phys_data = resp_physician.json()
    capsule_titles_phys = [c["title"] for c in phys_data["capsules"]]
    assert "blood_type record" in capsule_titles_phys
    assert "Medication list" in capsule_titles_phys


@pytest.mark.asyncio
async def test_qr_scan_creates_audit_log(client):
    """Successful scan writes an emergency_data_access audit entry."""
    patient_id = await _create_and_login(client, PATIENT)
    await _seed_health_capsule(patient_id, "blood_type record", "O negative", category="")

    beacon_resp = await client.post(f"/api/users/{patient_id}/emergency/beacon")
    assert beacon_resp.status_code == 200
    token = beacon_resp.json()["tokens"]["paramedic"]

    scan_resp = await client.get("/api/emergency/qr", params={"t": token, "p": "grandmarose"})
    assert scan_resp.status_code == 200
    audit_id = scan_resp.json()["audit_id"]

    async for db in get_db():
        entry = await db.get(AuditLog, audit_id)
        assert entry is not None
        assert entry.action == "emergency_data_access"
        assert entry.event_type == "emergency"
        assert entry.token_role == "paramedic"
        assert entry.decision == "allowed"
        break


@pytest.mark.asyncio
async def test_qr_scan_not_a_beacon_token_fails(client):
    """Org-issued token (aud = patient DID) is rejected by the beacon scanner."""
    # The scanner requires aud == "did:emergency:any"
    private_key, _ = generate_ed25519_keypair()
    non_beacon_token = create_ucan_token(
        issuer_did="did:key:z6MkFakeOrg",
        issuer_private_key=private_key,
        audience_did="did:key:z6MkActualPatient",
        role="paramedic",
        duration_seconds=1800,
        facts={},
    )
    resp = await client.get(
        "/api/emergency/qr", params={"t": non_beacon_token, "p": "grandmarose"}
    )
    assert resp.status_code == 403
    assert "beacon" in resp.text.lower()


@pytest.mark.asyncio
async def test_qr_scan_revoked_token(client):
    """Revoked beacon token returns 403."""
    patient_id = await _create_and_login(client, PATIENT)

    beacon_resp = await client.post(f"/api/users/{patient_id}/emergency/beacon")
    assert beacon_resp.status_code == 200
    token = beacon_resp.json()["tokens"]["er_nurse"]

    # Revoke the token (self-revocation via the existing revoke endpoint)
    revoke_resp = await client.post(
        "/api/emergency/revoke", json={"token": token, "reason": "test revocation"}
    )
    assert revoke_resp.status_code == 200

    scan_resp = await client.get("/api/emergency/qr", params={"t": token, "p": "grandmarose"})
    assert scan_resp.status_code == 403
    assert "revoked" in scan_resp.text.lower()
