"""Emergency access routes — UCAN-based scoped medical data access.

Flow:
1. Hospital issues UCAN token for a specific patient + role
2. Token is presented to access patient's scoped medical data
3. Everything is audit-logged and patient is notified
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import log_event, log_event_strict
from src.auth import get_current_user_id
from src import transit_bridge
from src.database import get_db
from src.gossip import load_capsules_decrypted
from src.models import Agent, KnowledgeCapsule, Network, NetworkMembership, Notification, UCANRevocation, User
from src.schemas import (
    EmergencyAccessRequest,
    EmergencyAccessResponse,
    EmergencyBeaconResponse,
    EmergencyRoleInfo,
    EmergencyTokenRequest,
    EmergencyTokenResponse,
)
from src.ucan import ROLE_SCOPES, capsule_matches_scope, create_ucan_token, token_hash, validate_ucan_token

router = APIRouter(prefix="/api/emergency", tags=["emergency"])

# Separate router for user-scoped beacon endpoint (/api/users/{user_id}/emergency/beacon)
beacon_router = APIRouter(prefix="/api/users", tags=["emergency"])


@router.get("/roles", response_model=list[EmergencyRoleInfo])
async def list_roles():
    """List available emergency access roles and their scopes."""
    return [
        EmergencyRoleInfo(role=role, categories=scope["categories"], keywords=scope["keywords"])
        for role, scope in ROLE_SCOPES.items()
    ]


@router.post("/token", response_model=EmergencyTokenResponse)
async def issue_token(
    data: EmergencyTokenRequest,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Issue a UCAN token for emergency access.

    The issuer must be a service/provider user with a loaded vault key and keypair.
    """
    if auth_user_id != data.issuer_user_id:
        raise HTTPException(403, "Access denied")

    # Validate issuer exists and is a service
    issuer_user = await db.get(User, data.issuer_user_id)
    if not issuer_user:
        raise HTTPException(404, "Issuer user not found")
    if issuer_user.user_type not in ("service", "organization"):
        raise HTTPException(403, "Only service providers can issue emergency tokens")

    # Get issuer's agent + keypair
    result = await db.execute(select(Agent).where(Agent.owner_id == data.issuer_user_id))
    issuer_agent = result.scalar_one_or_none()
    if not issuer_agent or not issuer_agent.did or not issuer_agent.encrypted_private_key:
        raise HTTPException(500, "Issuer agent has no cryptographic identity")

    # Decrypt issuer's private key using transit bridge
    if not transit_bridge.has_key(data.issuer_user_id):
        raise HTTPException(500, "Issuer vault key not loaded — log in first")

    try:
        issuer_private_key = transit_bridge.decrypt(data.issuer_user_id, issuer_agent.encrypted_private_key)
    except Exception:
        raise HTTPException(500, "Failed to decrypt issuer's private key")

    # Find patient by username
    patient_result = await db.execute(
        select(User).where(User.username == data.patient_username)
    )
    patient = patient_result.scalar_one_or_none()
    if not patient:
        raise HTTPException(403, "Emergency access denied")

    # Get patient's agent DID
    patient_agent_result = await db.execute(
        select(Agent).where(Agent.owner_id == patient.id)
    )
    patient_agent = patient_agent_result.scalar_one_or_none()
    if not patient_agent or not patient_agent.did:
        raise HTTPException(500, "Patient agent has no cryptographic identity")

    # Validate role
    if data.role not in ROLE_SCOPES:
        raise HTTPException(400, f"Invalid role. Valid roles: {list(ROLE_SCOPES.keys())}")

    # Rate limit: 3 tokens per hour per issuer:patient pair
    from src.rate_limit import check_emergency_issue_rate, record_emergency_issue
    rate_key = f"{data.issuer_user_id}:{patient.id}"
    rate_ok, rate_msg = check_emergency_issue_rate(rate_key)
    if not rate_ok:
        raise HTTPException(429, rate_msg)

    # Create UCAN token
    facts = {
        "practitioner_name": data.practitioner_name,
        "npi": data.npi,
        "case_id": data.case_id,
        "reason": data.reason,
        "institution": issuer_user.display_name,
    }

    token = create_ucan_token(
        issuer_did=issuer_agent.did,
        issuer_private_key=issuer_private_key,
        audience_did=patient_agent.did,
        role=data.role,
        duration_seconds=data.duration_seconds,
        facts=facts,
    )

    # Audit: token issuance (fail-safe — abort if audit write fails)
    await log_event_strict(
        db,
        actor_user_id=data.issuer_user_id,
        actor_did=issuer_agent.did,
        actor_role=data.role,
        actor_institution=issuer_user.display_name,
        target_user_id=patient.id,
        action="emergency_token_issued",
        event_type="emergency",
        token_hash=token_hash(token),
        token_role=data.role,
        case_id=data.case_id,
        reason=data.reason,
        decision="allowed",
        details=facts,
    )
    await db.commit()
    record_emergency_issue(rate_key)

    scope = ROLE_SCOPES[data.role]
    return EmergencyTokenResponse(
        token=token,
        issuer_did=issuer_agent.did,
        audience_did=patient_agent.did,
        role=data.role,
        expires_in=data.duration_seconds,
        scope=EmergencyRoleInfo(
            role=data.role,
            categories=scope["categories"],
            keywords=scope["keywords"],
        ),
    )


@router.post("/access", response_model=EmergencyAccessResponse)
async def access_patient_data(
    data: EmergencyAccessRequest,
    db: AsyncSession = Depends(get_db),
):
    """Present a UCAN token to access patient's scoped medical data.

    Validates token, filters capsules by role scope, logs everything.
    """
    # Find patient by username
    patient_result = await db.execute(
        select(User).where(User.username == data.patient_username)
    )
    patient = patient_result.scalar_one_or_none()
    if not patient:
        raise HTTPException(403, "Emergency access denied")

    # Get patient's agent for DID verification
    patient_agent_result = await db.execute(
        select(Agent).where(Agent.owner_id == patient.id)
    )
    patient_agent = patient_agent_result.scalar_one_or_none()
    if not patient_agent or not patient_agent.did:
        raise HTTPException(500, "Patient agent has no cryptographic identity")

    # Parse token to get issuer DID (we need it to find the issuer's public key)
    parts = data.token.split(".")
    if len(parts) != 2:
        await _log_denied(db, None, patient.id, data.token, "Invalid token format")
        raise HTTPException(403, "Invalid token format")

    import base64
    import json as json_mod
    try:
        payload_b64 = parts[0]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_data = json_mod.loads(base64.urlsafe_b64decode(payload_b64))
        issuer_did = payload_data.get("iss", "")
    except Exception:
        await _log_denied(db, None, patient.id, data.token, "Cannot parse token payload")
        raise HTTPException(403, "Cannot parse token")

    # Find issuer agent by DID
    issuer_agent_result = await db.execute(
        select(Agent).where(Agent.did == issuer_did)
    )
    issuer_agent = issuer_agent_result.scalar_one_or_none()
    if not issuer_agent or not issuer_agent.public_key:
        await _log_denied(db, None, patient.id, data.token, f"Unknown issuer DID: {issuer_did}")
        raise HTTPException(403, "Unknown issuer DID — not registered in TrustMesh")

    # Verify issuer is a service/provider
    issuer_user = await db.get(User, issuer_agent.owner_id)
    if not issuer_user or issuer_user.user_type not in ("service", "organization"):
        await _log_denied(db, issuer_agent.owner_id, patient.id, data.token, "Issuer is not a service provider")
        raise HTTPException(403, "Issuer is not a service provider")

    # Validate UCAN token (signature, expiry, audience)
    validation = validate_ucan_token(
        token=data.token,
        expected_audience_did=patient_agent.did,
        issuer_public_key=issuer_agent.public_key,
    )

    if not validation.valid:
        await _log_denied(
            db, issuer_agent.owner_id, patient.id, data.token,
            validation.error or "Token validation failed",
            actor_did=issuer_did,
            actor_institution=issuer_user.display_name,
        )
        raise HTTPException(403, validation.error or "Token validation failed")

    # Check if token has been revoked
    from src.ucan import is_token_revoked
    if await is_token_revoked(db, data.token):
        await _log_denied(
            db, issuer_agent.owner_id, patient.id, data.token,
            "Token has been revoked",
            actor_did=issuer_did,
            actor_institution=issuer_user.display_name,
        )
        raise HTTPException(403, "Token has been revoked")

    # Rate limit: 5 accesses per hour per token
    from src.rate_limit import check_emergency_present_rate, record_emergency_present
    t_hash = token_hash(data.token)
    rate_ok, rate_msg = check_emergency_present_rate(t_hash)
    if not rate_ok:
        raise HTTPException(429, rate_msg)

    payload = validation.payload
    role = payload.att.get("role", "")

    # Verify patient's vault key is loaded
    if not transit_bridge.has_key(patient.id):
        raise HTTPException(403, "Emergency access denied")

    # Load ALL patient capsules (not just public — emergency overrides trust tiers)
    capsule_result = await db.execute(
        select(KnowledgeCapsule.id).where(
            KnowledgeCapsule.owner_id == patient.id,
            KnowledgeCapsule.is_archived == False,  # noqa: E712
        )
    )
    all_capsule_ids = list(capsule_result.scalars().all())

    # Decrypt capsules
    all_capsules = await load_capsules_decrypted(db, all_capsule_ids, patient.id)

    # Filter by role scope AND emergency_accessible flag
    scoped_capsules = [
        c for c in all_capsules
        if capsule_matches_scope(c, role) and c.get("emergency_accessible", False)
    ]
    # Collect categories accessed
    categories = list(set(c.get("category", "") for c in scoped_capsules if c.get("category")))
    capsule_ids = [c["id"] for c in scoped_capsules]

    # Audit: emergency access (fail-safe — abort if audit write fails)
    expires_at = datetime.fromtimestamp(payload.exp, tz=timezone.utc)
    audit_entry = await log_event_strict(
        db,
        actor_user_id=issuer_agent.owner_id,
        actor_did=issuer_did,
        actor_role=role,
        actor_institution=issuer_user.display_name,
        target_user_id=patient.id,
        action="emergency_data_access",
        event_type="emergency",
        capsule_ids_accessed=capsule_ids,
        categories_accessed=categories,
        token_hash=token_hash(data.token),
        token_role=role,
        token_expires_at=expires_at,
        case_id=payload.fct.get("case_id", ""),
        reason=payload.fct.get("reason", ""),
        decision="allowed",
        details={
            "practitioner_name": payload.fct.get("practitioner_name", ""),
            "npi": payload.fct.get("npi", ""),
            "capsules_returned": len(scoped_capsules),
            "total_capsules": len(all_capsules),
        },
        notify_target=True,
        notification_title=f"Emergency access by {issuer_user.display_name}",
        notification_body=(
            f"Role: {role}. {len(scoped_capsules)} capsule(s) shared. "
            f"Practitioner: {payload.fct.get('practitioner_name', 'Unknown')}. "
            f"Reason: {payload.fct.get('reason', 'Not specified')}."
        ),
    )

    # ── Family Notification Relay ──
    # Notify all members of patient's family-type networks
    family_notified = await _notify_family_network(
        db,
        patient=patient,
        issuer_name=issuer_user.display_name,
        role=role,
        practitioner_name=payload.fct.get("practitioner_name", "Unknown"),
        reason=payload.fct.get("reason", "Not specified"),
        capsule_count=len(scoped_capsules),
    )

    await db.commit()
    record_emergency_present(t_hash)

    return EmergencyAccessResponse(
        patient_name=patient.display_name,
        role=role,
        capsules=scoped_capsules,
        capsule_count=len(scoped_capsules),
        categories=categories,
        audit_id=audit_entry.id,
        expires_at=expires_at,
        family_notified=family_notified,
    )


@router.post("/revoke")
async def revoke_emergency_token(
    data: dict,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Revoke an emergency token. Only the issuer can revoke their own tokens."""
    token = data.get("token")
    reason = data.get("reason", "")
    if not token:
        raise HTTPException(400, "Token is required")

    # Verify the token was issued by this user
    from src.ucan import token_hash as ucan_token_hash, is_token_revoked

    # Parse token to get issuer DID
    parts = token.split(".")
    if len(parts) != 2:
        raise HTTPException(400, "Invalid token format")

    import base64, json
    try:
        payload_b64 = parts[0]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes)
    except Exception:
        raise HTTPException(400, "Invalid token")

    issuer_did = payload.get("iss", "")

    # Verify the auth user owns this issuer DID
    issuer_agent = await db.execute(
        select(Agent).where(Agent.owner_id == auth_user_id)
    )
    agent = issuer_agent.scalar_one_or_none()
    if not agent or agent.did != issuer_did:
        raise HTTPException(403, "You can only revoke tokens you issued")

    # Check if already revoked
    t_hash = ucan_token_hash(token)
    already_revoked = await is_token_revoked(db, token)
    if already_revoked:
        return {"status": "already_revoked", "token_hash": t_hash}

    # Revoke
    revocation = UCANRevocation(
        token_hash=t_hash,
        revoked_by=auth_user_id,
        reason=reason,
    )
    db.add(revocation)

    # Audit
    await log_event_strict(
        db,
        actor_user_id=auth_user_id,
        target_user_id=payload.get("aud", ""),
        action="emergency_token_revoked",
        event_type="emergency",
        token_hash=t_hash,
        reason=reason,
        decision="allowed",
    )
    await db.commit()

    return {"status": "revoked", "token_hash": t_hash}


async def _notify_family_network(
    db: AsyncSession,
    patient: User,
    issuer_name: str,
    role: str,
    practitioner_name: str,
    reason: str,
    capsule_count: int,
) -> int:
    """Notify all members of the patient's family-type networks about emergency access.

    Returns the number of family members notified.
    """
    # Find family networks the patient belongs to
    family_nets = await db.execute(
        select(Network)
        .join(NetworkMembership, NetworkMembership.network_id == Network.id)
        .where(
            NetworkMembership.user_id == patient.id,
            Network.network_type == "family",
        )
    )
    family_networks = family_nets.scalars().all()

    if not family_networks:
        return 0

    # Get all members of these family networks (excluding the patient)
    notified = 0
    notified_user_ids = set()
    for network in family_networks:
        members_result = await db.execute(
            select(NetworkMembership.user_id).where(
                NetworkMembership.network_id == network.id,
                NetworkMembership.user_id != patient.id,
            )
        )
        for member_id in members_result.scalars().all():
            if member_id in notified_user_ids:
                continue
            notified_user_ids.add(member_id)

            notification = Notification(
                user_id=member_id,
                notification_type="emergency_family_alert",
                title=f"Emergency: {patient.display_name}'s medical data accessed",
                body=(
                    f"{issuer_name} accessed {patient.display_name}'s medical data "
                    f"({role}). {capsule_count} capsule(s) shared. "
                    f"Practitioner: {practitioner_name}. Reason: {reason}."
                ),
                related_id=patient.id,
            )
            db.add(notification)
            notified += 1

    return notified


async def _log_denied(
    db: AsyncSession,
    actor_user_id: str | None,
    target_user_id: str,
    token: str,
    reason: str,
    actor_did: str | None = None,
    actor_institution: str | None = None,
):
    """Log a denied emergency access attempt."""
    await log_event(
        db,
        actor_user_id=actor_user_id,
        actor_did=actor_did,
        actor_institution=actor_institution,
        target_user_id=target_user_id,
        action="emergency_access_denied",
        event_type="emergency",
        token_hash=token_hash(token),
        reason=reason,
        decision="denied",
        notify_target=True,
        notification_title="Emergency access denied",
        notification_body=f"An emergency access attempt was denied: {reason}",
    )
    await db.commit()


async def _verify_org_did(db: AsyncSession, org_did: str) -> bool:
    """Return True if org_did belongs to a registered medical organization.

    Checks local DB first (ghost users / local org users), then the public registry.
    """
    _MEDICAL_KEYWORDS = {"hospital", "medical", "health", "clinic", "ems", "emergency", "paramedic", "rescue", "urgent"}

    # 1. Local DB: ghost users or locally-registered org users with this DID
    local_result = await db.execute(
        select(Agent.did)
        .join(User, User.id == Agent.owner_id)
        .where(User.user_type.in_(["organization", "service"]))
        .where(Agent.did == org_did)
    )
    if local_result.scalar_one_or_none():
        return True  # In our federation — trust it

    # 2. Registry lookup by DID
    from src.federation import REGISTRY_URL
    if not REGISTRY_URL:
        return False

    import urllib.parse
    import httpx
    encoded = urllib.parse.quote(org_did, safe="")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{REGISTRY_URL.rstrip('/')}/api/agents/{encoded}")
            if resp.status_code == 200:
                entry = resp.json()
                name_lower = entry.get("name", "").lower()
                bio_lower = entry.get("bio", "").lower()
                return any(kw in name_lower or kw in bio_lower for kw in _MEDICAL_KEYWORDS)
    except Exception:
        pass
    return False


# ── Self-issued UCAN beacon endpoints ────────────────────────────────────────

_BEACON_ROLES: list[str] = ["paramedic", "er_nurse", "attending_physician"]
_BEACON_DURATION = 1800  # 30 minutes


@beacon_router.post("/{user_id}/emergency/beacon", response_model=EmergencyBeaconResponse)
async def generate_emergency_beacon(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Patient self-generates signed UCAN tokens for first-responder QR access.

    Returns one token per role (paramedic / er_nurse / attending_physician),
    each signed with the patient's own ed25519 key.  No issuing organisation required.
    """
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    # Rate limit: 3 beacon generations per hour
    from src.rate_limit import check_emergency_issue_rate, record_emergency_issue
    rate_ok, rate_msg = check_emergency_issue_rate(user_id)
    if not rate_ok:
        raise HTTPException(429, rate_msg)

    # Load agent + user info
    agent_result = await db.execute(
        select(Agent, User)
        .join(User, User.id == Agent.owner_id)
        .where(Agent.owner_id == user_id)
    )
    row = agent_result.first()
    if not row:
        raise HTTPException(404, "Agent not found for user")
    agent, user = row

    if not agent.did or not agent.encrypted_private_key:
        raise HTTPException(500, "Agent has no cryptographic identity")

    # Decrypt private key
    if not transit_bridge.has_key(user_id):
        raise HTTPException(503, "Vault key not loaded — log in first")

    try:
        private_key = transit_bridge.decrypt(user_id, agent.encrypted_private_key)
    except Exception:
        raise HTTPException(500, "Failed to decrypt agent private key")

    # Sign one token per role
    import uuid
    from datetime import datetime as _dt
    import os as _os
    from src.federation import POD_URL

    # TRUSTMESH_FRONTEND_URL lets multi-pod setups point QR codes at the shared
    # frontend (e.g. :3050) rather than the pod's own API port.  The &pod= param
    # tells the scanner which backend to call for token verification.
    _frontend_url = _os.getenv("TRUSTMESH_FRONTEND_URL", "http://localhost:3050").rstrip("/")

    patient_username = user.username or user_id
    tokens: dict[str, str] = {}
    qr_urls: dict[str, str] = {}

    for role in _BEACON_ROLES:
        token = create_ucan_token(
            issuer_did=agent.did,
            issuer_private_key=private_key,
            audience_did="did:emergency:any",
            role=role,
            duration_seconds=_BEACON_DURATION,
            facts={"emergency_beacon": True, "issued_by": user.display_name},
        )
        tokens[role] = token
        qr_urls[role] = (
            f"{_frontend_url}/emergency/scan"
            f"?t={token}&p={patient_username}&pod={POD_URL}"
        )

    # Zero private key bytes immediately
    private_key = b"\x00" * len(private_key)

    # Audit log (fail-safe)
    audit_id = str(uuid.uuid4())
    try:
        from src.models import AuditLog
        audit_row = AuditLog(
            id=audit_id,
            actor_user_id=user_id,
            target_user_id=user_id,
            action="emergency_beacon_generated",
            event_type="emergency",
            token_role="all_roles",
            decision="allowed",
        )
        db.add(audit_row)
        await db.commit()
    except Exception:
        pass  # Audit failure must not block beacon generation

    record_emergency_issue(user_id)

    # Count emergency-accessible capsules so the UI can show intake wizard if empty
    from sqlalchemy import func as _func
    from src.models import KnowledgeCapsule as _CapsuleModel
    capsule_count_result = await db.execute(
        select(_func.count(_CapsuleModel.id))
        .where(_CapsuleModel.owner_id == user_id)
        .where(_CapsuleModel.emergency_accessible == True)
    )
    capsule_count = capsule_count_result.scalar() or 0

    return EmergencyBeaconResponse(
        tokens=tokens,
        qr_urls=qr_urls,
        patient_did=agent.did,
        patient_name=user.display_name,
        pod_url=POD_URL,
        expires_in=_BEACON_DURATION,
        generated_at=_dt.now(tz=timezone.utc).isoformat(),
        audit_id=audit_id,
        capsule_count=capsule_count,
    )


@router.get("/qr", response_model=EmergencyAccessResponse)
async def scan_emergency_qr(
    t: str,
    p: str,
    db: AsyncSession = Depends(get_db),
):
    """First-responder endpoint: validate a self-issued beacon token and return scoped records.

    No login required. Token is validated via ed25519 signature against the patient's public key.
    """
    import base64
    import json as _json

    if len(t) > 4096 or len(p) > 50:
        raise HTTPException(400, "Invalid parameters")

    # Parse token
    parts = t.split(".")
    if len(parts) != 2:
        raise HTTPException(403, "Invalid token format")

    payload_b64, sig_b64 = parts
    try:
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload_data = _json.loads(payload_bytes)
    except Exception:
        raise HTTPException(403, "Cannot parse token payload")

    # Check expiry and beacon sentinel
    exp = payload_data.get("exp", 0)
    if exp < int(datetime.now(tz=timezone.utc).timestamp()):
        raise HTTPException(403, "Token expired")

    aud = payload_data.get("aud", "")
    if aud != "did:emergency:any" and not aud.startswith("did:"):
        raise HTTPException(403, "Not a beacon token")
    org_targeted = aud != "did:emergency:any"  # True → must verify org at scan time

    if not payload_data.get("fct", {}).get("emergency_beacon"):
        raise HTTPException(403, "Not a beacon token")

    role = payload_data.get("att", {}).get("role", "")
    if role not in ROLE_SCOPES:
        raise HTTPException(403, f"Unknown role: {role}")

    # Find patient by username
    patient_result = await db.execute(select(User).where(User.username == p))
    patient = patient_result.scalar_one_or_none()
    if not patient:
        raise HTTPException(403, "Patient not found")

    patient_agent_result = await db.execute(select(Agent).where(Agent.owner_id == patient.id))
    patient_agent = patient_agent_result.scalar_one_or_none()
    if not patient_agent or not patient_agent.public_key or not patient_agent.did:
        raise HTTPException(500, "Patient has no cryptographic identity")

    # Verify self-issued: iss must equal patient's DID
    iss = payload_data.get("iss", "")
    if iss != patient_agent.did:
        await _log_denied(db, None, patient.id, t, "Issuer DID does not match patient")
        raise HTTPException(403, "Issuer mismatch")

    # For org-targeted tokens: verify the audience DID is a registered medical provider
    if org_targeted:
        org_ok = await _verify_org_did(db, aud)
        if not org_ok:
            await _log_denied(
                db, patient.id, patient.id, t,
                f"Org DID not registered as medical provider: {aud}",
            )
            raise HTTPException(403, "Organization not verified as medical provider")

    # Verify signature
    try:
        padding = 4 - len(sig_b64) % 4
        if padding != 4:
            sig_b64 += "=" * padding
        signature = base64.urlsafe_b64decode(sig_b64)
    except Exception:
        await _log_denied(db, patient.id, patient.id, t, "Invalid signature encoding")
        raise HTTPException(403, "Invalid token signature")

    from src.crypto import verify_ed25519
    if not verify_ed25519(payload_bytes, signature, patient_agent.public_key):
        await _log_denied(db, patient.id, patient.id, t, "Signature verification failed")
        raise HTTPException(403, "Invalid token signature")

    # Check revocation
    from src.ucan import is_token_revoked
    if await is_token_revoked(db, t):
        await _log_denied(db, patient.id, patient.id, t, "Token revoked")
        raise HTTPException(403, "Token has been revoked")

    # Rate limit per token hash
    from src.rate_limit import check_emergency_present_rate, record_emergency_present
    t_hash = token_hash(t)
    rate_ok, rate_msg = check_emergency_present_rate(t_hash)
    if not rate_ok:
        raise HTTPException(429, rate_msg)

    # Vault must be loaded
    if not transit_bridge.has_key(patient.id):
        raise HTTPException(503, "Patient vault not available")

    # Fetch emergency-accessible capsules
    capsule_result = await db.execute(
        select(KnowledgeCapsule.id).where(
            KnowledgeCapsule.owner_id == patient.id,
            KnowledgeCapsule.is_archived.is_(False),
            KnowledgeCapsule.emergency_accessible.is_(True),
        )
    )
    all_capsule_ids = list(capsule_result.scalars().all())
    all_capsules = await load_capsules_decrypted(db, all_capsule_ids, patient.id)

    scoped = [c for c in all_capsules if capsule_matches_scope(c, role)]
    categories = list({c.get("category", "") for c in scoped if c.get("category")})
    capsule_ids = [c["id"] for c in scoped]

    # Audit (fail-safe)
    import uuid
    exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
    audit_entry = await log_event_strict(
        db,
        actor_user_id=patient.id,
        actor_did=iss,
        actor_role=role,
        target_user_id=patient.id,
        action="emergency_data_access",
        event_type="emergency",
        token_hash=t_hash,
        token_role=role,
        token_expires_at=exp_dt,
        capsule_ids_accessed=capsule_ids,
        categories_accessed=categories,
        decision="allowed",
        details={"beacon": True, "capsules_returned": len(scoped)},
        notify_target=True,
        notification_title="Emergency beacon scanned",
        notification_body=f"Role: {role}. {len(scoped)} record(s) accessed.",
    )

    family_notified = await _notify_family_network(
        db,
        patient=patient,
        issuer_name=payload_data.get("fct", {}).get("issued_by", patient.display_name),
        role=role,
        practitioner_name="(first responder)",
        reason="emergency beacon scan",
        capsule_count=len(scoped),
    )

    await db.commit()
    record_emergency_present(t_hash)

    return EmergencyAccessResponse(
        patient_name=patient.display_name,
        role=role,
        capsules=scoped,
        capsule_count=len(scoped),
        total_capsules=len(all_capsules),
        categories=categories,
        audit_id=audit_entry.id,
        expires_at=exp_dt,
        family_notified=family_notified,
    )
