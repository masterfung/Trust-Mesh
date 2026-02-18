"""FHIR R4 interoperability routes — translate TrustMesh capsules to standard healthcare format."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db
from src.fhir import build_bundle, capsule_to_fhir, patient_to_fhir
from src.gossip import load_capsules_decrypted
from src.models import AuditLog, KnowledgeCapsule, User

router = APIRouter(prefix="/api", tags=["fhir"])


@router.get("/users/{user_id}/fhir/Patient")
async def fhir_patient(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """FHIR R4 Patient resource for a user."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    return patient_to_fhir({
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    })


@router.get("/users/{user_id}/fhir/Bundle")
async def fhir_bundle(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """FHIR R4 Bundle of all health capsules for a user."""
    if auth_user_id != user_id:
        raise HTTPException(403, "Access denied")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    from src import transit_bridge
    if not transit_bridge.has_key(user_id):
        raise HTTPException(500, "Vault key not loaded")

    # Get all health-category capsules
    result = await db.execute(
        select(KnowledgeCapsule.id).where(
            KnowledgeCapsule.owner_id == user_id,
            KnowledgeCapsule.category == "health",
            KnowledgeCapsule.is_archived == False,  # noqa: E712
        )
    )
    capsule_ids = list(result.scalars().all())
    capsules = await load_capsules_decrypted(db, capsule_ids, user_id)

    # Convert to FHIR resources
    patient = patient_to_fhir({
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    })
    resources = []
    for c in capsules:
        fhir_resource = capsule_to_fhir(c, user.id)
        if fhir_resource:
            resources.append(fhir_resource)

    return build_bundle(patient, resources)


@router.get("/emergency/{audit_id}/fhir")
async def emergency_fhir_bundle(
    audit_id: str,
    db: AsyncSession = Depends(get_db),
):
    """FHIR R4 Bundle for an emergency access event.

    Publicly accessible (authenticated by the audit_id reference).
    Returns the same capsules that were shared during the emergency access.
    """
    # Look up the audit log entry
    audit = await db.get(AuditLog, audit_id)
    if not audit or audit.action != "emergency_data_access":
        raise HTTPException(404, "Emergency access record not found")

    patient = await db.get(User, audit.target_user_id)
    if not patient:
        raise HTTPException(404, "Patient not found")

    from src import transit_bridge
    if not transit_bridge.has_key(patient.id):
        raise HTTPException(500, "Patient vault key not loaded")

    # Get the capsule IDs from the audit record
    capsule_ids = json.loads(audit.capsule_ids_accessed) if audit.capsule_ids_accessed else []
    if not capsule_ids:
        # Fallback: re-query health capsules
        result = await db.execute(
            select(KnowledgeCapsule.id).where(
                KnowledgeCapsule.owner_id == patient.id,
                KnowledgeCapsule.category == "health",
                KnowledgeCapsule.emergency_accessible == True,  # noqa: E712
                KnowledgeCapsule.is_archived == False,  # noqa: E712
            )
        )
        capsule_ids = list(result.scalars().all())

    capsules = await load_capsules_decrypted(db, capsule_ids, patient.id)

    # Build FHIR bundle
    patient_resource = patient_to_fhir({
        "id": patient.id,
        "username": patient.username,
        "display_name": patient.display_name,
    })
    resources = []
    for c in capsules:
        fhir_resource = capsule_to_fhir(c, patient.id)
        if fhir_resource:
            resources.append(fhir_resource)

    bundle = build_bundle(patient_resource, resources, bundle_type="document")
    # Add emergency access metadata
    bundle["_trustmesh_emergency"] = {
        "audit_id": audit_id,
        "access_role": audit.token_role,
        "institution": audit.actor_institution,
        "case_id": audit.case_id,
    }

    return bundle
