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

from src.audit import log_event
from src.auth import get_current_user_id
from src.crypto import decrypt
from src.database import get_db
from src.gossip import load_capsules_decrypted
from src.models import Agent, KnowledgeCapsule, Network, NetworkMembership, Notification, User
from src.schemas import (
    EmergencyAccessRequest,
    EmergencyAccessResponse,
    EmergencyRoleInfo,
    EmergencyTokenRequest,
    EmergencyTokenResponse,
)
from src.ucan import ROLE_SCOPES, capsule_matches_scope, create_ucan_token, token_hash, validate_ucan_token

router = APIRouter(prefix="/api/emergency", tags=["emergency"])


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
    from src.main import vault_keys

    if auth_user_id != data.issuer_user_id:
        raise HTTPException(403, "Access denied")

    # Validate issuer exists and is a service
    issuer_user = await db.get(User, data.issuer_user_id)
    if not issuer_user:
        raise HTTPException(404, "Issuer user not found")
    if issuer_user.user_type != "service":
        raise HTTPException(403, "Only service providers can issue emergency tokens")

    # Get issuer's agent + keypair
    result = await db.execute(select(Agent).where(Agent.owner_id == data.issuer_user_id))
    issuer_agent = result.scalar_one_or_none()
    if not issuer_agent or not issuer_agent.did or not issuer_agent.encrypted_private_key:
        raise HTTPException(500, "Issuer agent has no cryptographic identity")

    # Decrypt issuer's private key
    vault_key = vault_keys.get(data.issuer_user_id)
    if not vault_key:
        raise HTTPException(500, "Issuer vault key not loaded — log in first")

    try:
        issuer_private_key = decrypt(issuer_agent.encrypted_private_key, vault_key)
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

    # Audit: token issuance
    await log_event(
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
    from src.main import vault_keys

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
    if not issuer_user or issuer_user.user_type != "service":
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

    payload = validation.payload
    role = payload.att.get("role", "")

    # Get patient's vault key
    vault_key = vault_keys.get(patient.id)
    if not vault_key:
        raise HTTPException(500, "Patient vault key not loaded")

    # Load ALL patient capsules (not just public — emergency overrides trust tiers)
    capsule_result = await db.execute(
        select(KnowledgeCapsule.id).where(
            KnowledgeCapsule.owner_id == patient.id,
            KnowledgeCapsule.is_archived == False,  # noqa: E712
        )
    )
    all_capsule_ids = list(capsule_result.scalars().all())

    # Decrypt capsules
    all_capsules = await load_capsules_decrypted(db, all_capsule_ids, vault_key)

    # Filter by role scope AND emergency_accessible flag
    scoped_capsules = [
        c for c in all_capsules
        if capsule_matches_scope(c, role) and c.get("emergency_accessible", False)
    ]
    # Fallback: if no capsules have emergency_accessible set, use old behavior (scope only)
    # This handles data seeded before the flag existed
    if not scoped_capsules:
        scoped_capsules = [c for c in all_capsules if capsule_matches_scope(c, role)]

    # Collect categories accessed
    categories = list(set(c.get("category", "") for c in scoped_capsules if c.get("category")))
    capsule_ids = [c["id"] for c in scoped_capsules]

    # Audit: emergency access
    expires_at = datetime.fromtimestamp(payload.exp, tz=timezone.utc)
    audit_entry = await log_event(
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
