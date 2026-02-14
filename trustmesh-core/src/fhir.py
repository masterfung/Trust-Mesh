"""FHIR R4 resource mappers — translate TrustMesh capsules to standard healthcare format.

No external library needed: FHIR R4 is just JSON structures.
"""

import uuid
from datetime import datetime, timezone


def _fhir_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def capsule_to_fhir(capsule: dict, patient_id: str) -> dict | None:
    """Convert a capsule to the most appropriate FHIR R4 resource.

    Returns None if the capsule doesn't map to a FHIR resource.
    """
    category = (capsule.get("category") or "").lower()
    title = (capsule.get("title") or "").lower()
    content = capsule.get("content", "")

    # Allergy detection
    if "allergy" in title or "allergies" in title or "allergic" in content.lower():
        return _to_allergy_intolerance(capsule, patient_id)

    # Medication detection
    if "medication" in title or "medicine" in title or "prescription" in content.lower():
        return _to_medication_statement(capsule, patient_id)

    # Medical condition detection
    if category == "health" and any(kw in title for kw in [
        "condition", "diagnosis", "disease", "disorder", "blood pressure",
        "dialysis", "diabetes", "dnr", "medical",
    ]):
        return _to_condition(capsule, patient_id)

    # Emergency contacts
    if "emergency contact" in title or "emergency_contact" in title:
        return _to_emergency_contact(capsule, patient_id)

    # General health capsule -> Observation
    if category == "health":
        return _to_observation(capsule, patient_id)

    return None


def _to_allergy_intolerance(capsule: dict, patient_id: str) -> dict:
    """Map allergy capsule to FHIR AllergyIntolerance."""
    content = capsule.get("content", "")

    # Try to extract specific allergens from content
    substances = _extract_substances(content)

    return {
        "resourceType": "AllergyIntolerance",
        "id": _fhir_id(),
        "meta": {"lastUpdated": _now_iso()},
        "clinicalStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]
        },
        "verificationStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification", "code": "unconfirmed"}]
        },
        "type": "allergy",
        "category": ["medication"] if any(kw in content.lower() for kw in ["penicillin", "aspirin", "ibuprofen"]) else ["food"],
        "patient": {"reference": f"Patient/{patient_id}"},
        "note": [{"text": content}],
        "code": {"text": capsule.get("title", "Unknown allergy")},
        "_trustmesh": {
            "capsule_id": capsule.get("id"),
            "visibility": capsule.get("visibility"),
            "emergency_accessible": capsule.get("emergency_accessible"),
            "substances": substances,
        },
    }


def _to_medication_statement(capsule: dict, patient_id: str) -> dict:
    """Map medication capsule to FHIR MedicationStatement."""
    return {
        "resourceType": "MedicationStatement",
        "id": _fhir_id(),
        "meta": {"lastUpdated": _now_iso()},
        "status": "active",
        "subject": {"reference": f"Patient/{patient_id}"},
        "medicationCodeableConcept": {"text": capsule.get("title", "Medications")},
        "note": [{"text": capsule.get("content", "")}],
        "dateAsserted": _now_iso(),
        "_trustmesh": {
            "capsule_id": capsule.get("id"),
            "visibility": capsule.get("visibility"),
            "emergency_accessible": capsule.get("emergency_accessible"),
        },
    }


def _to_condition(capsule: dict, patient_id: str) -> dict:
    """Map condition capsule to FHIR Condition."""
    return {
        "resourceType": "Condition",
        "id": _fhir_id(),
        "meta": {"lastUpdated": _now_iso()},
        "clinicalStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {"text": capsule.get("title", "Unknown condition")},
        "note": [{"text": capsule.get("content", "")}],
        "_trustmesh": {
            "capsule_id": capsule.get("id"),
            "visibility": capsule.get("visibility"),
            "emergency_accessible": capsule.get("emergency_accessible"),
        },
    }


def _to_observation(capsule: dict, patient_id: str) -> dict:
    """Map health capsule to FHIR Observation (generic)."""
    return {
        "resourceType": "Observation",
        "id": _fhir_id(),
        "meta": {"lastUpdated": _now_iso()},
        "status": "final",
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {"text": capsule.get("title", "Health observation")},
        "valueString": capsule.get("content", ""),
        "_trustmesh": {
            "capsule_id": capsule.get("id"),
            "visibility": capsule.get("visibility"),
            "emergency_accessible": capsule.get("emergency_accessible"),
        },
    }


def _to_emergency_contact(capsule: dict, patient_id: str) -> dict:
    """Map emergency contact capsule to FHIR RelatedPerson."""
    return {
        "resourceType": "RelatedPerson",
        "id": _fhir_id(),
        "meta": {"lastUpdated": _now_iso()},
        "patient": {"reference": f"Patient/{patient_id}"},
        "name": [{"text": capsule.get("title", "Emergency Contact")}],
        "relationship": [{"text": "emergency contact"}],
        "communication": [{"text": capsule.get("content", "")}],
        "_trustmesh": {
            "capsule_id": capsule.get("id"),
        },
    }


def patient_to_fhir(user: dict) -> dict:
    """Convert a TrustMesh user to FHIR Patient resource."""
    name_parts = user.get("display_name", "").split()
    return {
        "resourceType": "Patient",
        "id": user.get("id", _fhir_id()),
        "meta": {"lastUpdated": _now_iso()},
        "name": [{
            "use": "official",
            "text": user.get("display_name", ""),
            "given": name_parts[:1],
            "family": name_parts[-1] if len(name_parts) > 1 else "",
        }],
        "active": True,
        "_trustmesh": {
            "username": user.get("username"),
            "user_id": user.get("id"),
        },
    }


def build_bundle(patient: dict, resources: list[dict], bundle_type: str = "collection") -> dict:
    """Build a FHIR R4 Bundle from patient + resource list."""
    entries = [{"resource": patient, "fullUrl": f"urn:uuid:{patient['id']}"}]
    for r in resources:
        entries.append({"resource": r, "fullUrl": f"urn:uuid:{r['id']}"})

    return {
        "resourceType": "Bundle",
        "id": _fhir_id(),
        "meta": {"lastUpdated": _now_iso()},
        "type": bundle_type,
        "total": len(entries),
        "entry": entries,
    }


def _extract_substances(content: str) -> list[str]:
    """Extract substance/allergen names from free text."""
    common_allergens = [
        "penicillin", "aspirin", "ibuprofen", "sulfa", "latex",
        "peanut", "tree nut", "shellfish", "fish", "egg", "milk",
        "soy", "wheat", "gluten", "bee sting", "morphine", "codeine",
    ]
    found = []
    content_lower = content.lower()
    for allergen in common_allergens:
        if allergen in content_lower:
            found.append(allergen)
    return found
