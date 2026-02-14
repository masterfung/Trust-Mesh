"""Tests for FHIR R4 integration: capsule-to-FHIR mapping, patient resource,
bundle construction, and API endpoints.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.auth import sessions, _login_attempts
from src.database import init_db, drop_db
from src.fhir import build_bundle, capsule_to_fhir, patient_to_fhir
from src.rate_limit import _connection_limiter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Reset DB, auth state, and rate limiters for each test."""
    sessions.clear()
    _login_attempts.clear()
    _connection_limiter._events.clear()

    from src.main import vault_keys, pin_tokens
    vault_keys.clear()
    pin_tokens.clear()

    await drop_db()
    await init_db()
    yield
    await drop_db()


def _make_transport():
    from src.main import app
    return ASGITransport(app=app)


@pytest_asyncio.fixture
async def client():
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def anon_client():
    transport = _make_transport()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_USER = {
    "username": "fhir_user",
    "display_name": "John Doe",
    "bio": "",
    "password": "SecureTestPass1!",
}

VALID_USER_B = {
    "username": "fhir_user_b",
    "display_name": "Jane Smith",
    "bio": "",
    "password": "SecureTestPass2!",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def signup_user(client: AsyncClient, user_data: dict) -> tuple[dict, dict]:
    resp = await client.post("/api/users", json=user_data)
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    cookies = dict(resp.cookies)
    return resp.json(), cookies


async def create_capsule(
    client: AsyncClient, user_id: str, cookies: dict, payload: dict,
) -> dict:
    resp = await client.post(
        f"/api/users/{user_id}/capsules", json=payload, cookies=cookies,
    )
    assert resp.status_code == 200, f"Create capsule failed: {resp.text}"
    return resp.json()


# ===================================================================
# UNIT TESTS: capsule_to_fhir()
# ===================================================================


@pytest.mark.asyncio
async def test_capsule_to_fhir_allergy():
    """Allergy capsule maps to FHIR AllergyIntolerance."""
    capsule = {
        "id": "cap-001",
        "title": "Allergy Information",
        "content": "Allergic to penicillin and shellfish.",
        "category": "health",
        "visibility": "internal",
        "emergency_accessible": True,
    }

    result = capsule_to_fhir(capsule, "patient-123")

    assert result is not None
    assert result["resourceType"] == "AllergyIntolerance"
    assert result["patient"]["reference"] == "Patient/patient-123"
    assert result["note"][0]["text"] == "Allergic to penicillin and shellfish."
    assert result["code"]["text"] == "Allergy Information"
    assert result["type"] == "allergy"
    # TrustMesh extension
    assert result["_trustmesh"]["capsule_id"] == "cap-001"
    assert result["_trustmesh"]["visibility"] == "internal"
    assert result["_trustmesh"]["emergency_accessible"] is True
    # Should detect penicillin and shellfish as substances
    assert "penicillin" in result["_trustmesh"]["substances"]
    assert "shellfish" in result["_trustmesh"]["substances"]


@pytest.mark.asyncio
async def test_capsule_to_fhir_allergy_medication_category():
    """Allergy capsule with medication allergen gets category=['medication']."""
    capsule = {
        "id": "cap-002",
        "title": "Drug Allergies",
        "content": "Patient is allergic to penicillin.",
        "category": "health",
        "visibility": "private",
        "emergency_accessible": False,
    }

    result = capsule_to_fhir(capsule, "patient-123")

    assert result is not None
    assert result["resourceType"] == "AllergyIntolerance"
    assert result["category"] == ["medication"]


@pytest.mark.asyncio
async def test_capsule_to_fhir_allergy_food_category():
    """Allergy capsule with food allergen gets category=['food']."""
    capsule = {
        "id": "cap-003",
        "title": "Food Allergies",
        "content": "Severe peanut allergy.",
        "category": "health",
        "visibility": "private",
        "emergency_accessible": True,
    }

    result = capsule_to_fhir(capsule, "patient-123")

    assert result is not None
    assert result["resourceType"] == "AllergyIntolerance"
    assert result["category"] == ["food"]


@pytest.mark.asyncio
async def test_capsule_to_fhir_medication():
    """Medication capsule maps to FHIR MedicationStatement."""
    capsule = {
        "id": "cap-010",
        "title": "Current Medications",
        "content": "Lisinopril 10mg daily, Metformin 500mg twice daily.",
        "category": "health",
        "visibility": "internal",
        "emergency_accessible": True,
    }

    result = capsule_to_fhir(capsule, "patient-456")

    assert result is not None
    assert result["resourceType"] == "MedicationStatement"
    assert result["status"] == "active"
    assert result["subject"]["reference"] == "Patient/patient-456"
    assert result["medicationCodeableConcept"]["text"] == "Current Medications"
    assert result["note"][0]["text"] == "Lisinopril 10mg daily, Metformin 500mg twice daily."
    assert result["_trustmesh"]["capsule_id"] == "cap-010"


@pytest.mark.asyncio
async def test_capsule_to_fhir_medication_by_content():
    """Capsule with 'prescription' in content maps to MedicationStatement."""
    capsule = {
        "id": "cap-011",
        "title": "Daily Routine",
        "content": "My prescription includes blood pressure medicine.",
        "category": "health",
        "visibility": "private",
        "emergency_accessible": False,
    }

    result = capsule_to_fhir(capsule, "patient-789")

    assert result is not None
    assert result["resourceType"] == "MedicationStatement"


@pytest.mark.asyncio
async def test_capsule_to_fhir_condition():
    """Condition capsule maps to FHIR Condition."""
    capsule = {
        "id": "cap-020",
        "title": "Medical Condition: Diabetes Type 2",
        "content": "Diagnosed with Type 2 diabetes in 2020. Managing with diet and medication.",
        "category": "health",
        "visibility": "shareable",
        "emergency_accessible": True,
    }

    result = capsule_to_fhir(capsule, "patient-123")

    assert result is not None
    assert result["resourceType"] == "Condition"
    assert result["subject"]["reference"] == "Patient/patient-123"
    assert result["code"]["text"] == "Medical Condition: Diabetes Type 2"
    assert "diabetes" in result["note"][0]["text"].lower()
    assert result["clinicalStatus"]["coding"][0]["code"] == "active"
    assert result["_trustmesh"]["capsule_id"] == "cap-020"


@pytest.mark.asyncio
async def test_capsule_to_fhir_condition_blood_pressure():
    """Blood pressure capsule maps to Condition (category=health + keyword match)."""
    capsule = {
        "id": "cap-021",
        "title": "Blood Pressure History",
        "content": "Hypertension diagnosed 2019. Currently controlled.",
        "category": "health",
        "visibility": "internal",
        "emergency_accessible": False,
    }

    result = capsule_to_fhir(capsule, "patient-123")

    assert result is not None
    assert result["resourceType"] == "Condition"


@pytest.mark.asyncio
async def test_capsule_to_fhir_condition_dnr():
    """DNR capsule maps to Condition (category=health + 'dnr' keyword)."""
    capsule = {
        "id": "cap-022",
        "title": "DNR Order",
        "content": "Do Not Resuscitate order signed 2024.",
        "category": "health",
        "visibility": "open",
        "emergency_accessible": True,
    }

    result = capsule_to_fhir(capsule, "patient-123")

    assert result is not None
    assert result["resourceType"] == "Condition"


@pytest.mark.asyncio
async def test_capsule_to_fhir_non_health():
    """Non-health capsule returns None."""
    capsule = {
        "id": "cap-030",
        "title": "Favorite Recipes",
        "content": "Best pasta recipe from grandma.",
        "category": "personal",
        "visibility": "private",
        "emergency_accessible": False,
    }

    result = capsule_to_fhir(capsule, "patient-123")

    assert result is None


@pytest.mark.asyncio
async def test_capsule_to_fhir_no_category():
    """Capsule with no category and non-health title returns None."""
    capsule = {
        "id": "cap-031",
        "title": "Shopping List",
        "content": "Buy milk, eggs, bread.",
        "category": "",
        "visibility": "private",
        "emergency_accessible": False,
    }

    result = capsule_to_fhir(capsule, "patient-123")

    assert result is None


@pytest.mark.asyncio
async def test_capsule_to_fhir_health_observation():
    """Health capsule without specific keywords maps to Observation."""
    capsule = {
        "id": "cap-040",
        "title": "General Health Notes",
        "content": "Feeling good this week. Sleeping well.",
        "category": "health",
        "visibility": "private",
        "emergency_accessible": False,
    }

    result = capsule_to_fhir(capsule, "patient-123")

    assert result is not None
    assert result["resourceType"] == "Observation"
    assert result["status"] == "final"
    assert result["subject"]["reference"] == "Patient/patient-123"
    assert result["valueString"] == "Feeling good this week. Sleeping well."


# ===================================================================
# UNIT TESTS: patient_to_fhir()
# ===================================================================


@pytest.mark.asyncio
async def test_patient_to_fhir_basic():
    """patient_to_fhir produces valid FHIR Patient resource."""
    user_data = {
        "id": "user-001",
        "username": "johndoe",
        "display_name": "John Doe",
    }

    result = patient_to_fhir(user_data)

    assert result["resourceType"] == "Patient"
    assert result["id"] == "user-001"
    assert result["active"] is True
    assert result["name"][0]["use"] == "official"
    assert result["name"][0]["text"] == "John Doe"
    assert result["name"][0]["given"] == ["John"]
    assert result["name"][0]["family"] == "Doe"
    assert result["meta"]["lastUpdated"] is not None
    assert result["_trustmesh"]["username"] == "johndoe"
    assert result["_trustmesh"]["user_id"] == "user-001"


@pytest.mark.asyncio
async def test_patient_to_fhir_single_name():
    """patient_to_fhir handles single-word display name."""
    user_data = {
        "id": "user-002",
        "username": "cher",
        "display_name": "Cher",
    }

    result = patient_to_fhir(user_data)

    assert result["name"][0]["given"] == ["Cher"]
    assert result["name"][0]["family"] == ""


@pytest.mark.asyncio
async def test_patient_to_fhir_multi_name():
    """patient_to_fhir handles multi-part display name (family = last part)."""
    user_data = {
        "id": "user-003",
        "username": "janesmith",
        "display_name": "Mary Jane Watson",
    }

    result = patient_to_fhir(user_data)

    assert result["name"][0]["text"] == "Mary Jane Watson"
    assert result["name"][0]["given"] == ["Mary"]
    assert result["name"][0]["family"] == "Watson"


@pytest.mark.asyncio
async def test_patient_to_fhir_empty_name():
    """patient_to_fhir handles empty display name gracefully."""
    user_data = {
        "id": "user-004",
        "username": "anon",
        "display_name": "",
    }

    result = patient_to_fhir(user_data)

    assert result["resourceType"] == "Patient"
    assert result["name"][0]["text"] == ""


# ===================================================================
# UNIT TESTS: build_bundle()
# ===================================================================


@pytest.mark.asyncio
async def test_build_bundle_structure():
    """build_bundle produces valid FHIR Bundle structure."""
    patient = {
        "resourceType": "Patient",
        "id": "patient-001",
        "active": True,
    }
    resources = [
        {"resourceType": "AllergyIntolerance", "id": "allergy-001"},
        {"resourceType": "MedicationStatement", "id": "med-001"},
    ]

    bundle = build_bundle(patient, resources)

    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert bundle["total"] == 3  # patient + 2 resources
    assert len(bundle["entry"]) == 3
    assert bundle["id"] is not None
    assert bundle["meta"]["lastUpdated"] is not None


@pytest.mark.asyncio
async def test_build_bundle_entries_contain_resources():
    """build_bundle entries contain full resources with fullUrl."""
    patient = {"resourceType": "Patient", "id": "p-001"}
    resources = [{"resourceType": "Condition", "id": "c-001"}]

    bundle = build_bundle(patient, resources)

    # First entry is the patient
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"
    assert bundle["entry"][0]["fullUrl"] == "urn:uuid:p-001"

    # Second entry is the condition
    assert bundle["entry"][1]["resource"]["resourceType"] == "Condition"
    assert bundle["entry"][1]["fullUrl"] == "urn:uuid:c-001"


@pytest.mark.asyncio
async def test_build_bundle_empty_resources():
    """build_bundle with no resources contains only the patient."""
    patient = {"resourceType": "Patient", "id": "p-002"}

    bundle = build_bundle(patient, [])

    assert bundle["total"] == 1
    assert len(bundle["entry"]) == 1
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"


@pytest.mark.asyncio
async def test_build_bundle_custom_type():
    """build_bundle with custom bundle_type uses provided type."""
    patient = {"resourceType": "Patient", "id": "p-003"}

    bundle = build_bundle(patient, [], bundle_type="document")

    assert bundle["type"] == "document"


# ===================================================================
# API ENDPOINT TESTS: GET /api/users/{user_id}/fhir/Patient
# ===================================================================


@pytest.mark.asyncio
async def test_fhir_patient_endpoint(client):
    """GET /api/users/{user_id}/fhir/Patient returns valid FHIR Patient."""
    user, cookies = await signup_user(client, VALID_USER)

    resp = await client.get(
        f"/api/users/{user['id']}/fhir/Patient",
        cookies=cookies,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["resourceType"] == "Patient"
    assert data["id"] == user["id"]
    assert data["name"][0]["text"] == "John Doe"
    assert data["active"] is True
    assert data["_trustmesh"]["username"] == "fhir_user"


@pytest.mark.asyncio
async def test_fhir_patient_endpoint_no_auth(anon_client, client):
    """GET /api/users/{user_id}/fhir/Patient without auth returns 401."""
    user, _cookies = await signup_user(client, VALID_USER)

    resp = await anon_client.get(
        f"/api/users/{user['id']}/fhir/Patient",
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_fhir_patient_endpoint_wrong_user(client):
    """GET /api/users/{user_id}/fhir/Patient as another user returns 403."""
    user_a, _cookies_a = await signup_user(client, VALID_USER)
    _user_b, cookies_b = await signup_user(client, VALID_USER_B)

    resp = await client.get(
        f"/api/users/{user_a['id']}/fhir/Patient",
        cookies=cookies_b,
    )
    assert resp.status_code == 403


# ===================================================================
# API ENDPOINT TESTS: GET /api/users/{user_id}/fhir/Bundle
# ===================================================================


@pytest.mark.asyncio
async def test_fhir_bundle_endpoint_with_health_capsules(client):
    """GET /api/users/{user_id}/fhir/Bundle returns bundle with health capsules."""
    user, cookies = await signup_user(client, VALID_USER)

    # Create health capsules
    await create_capsule(client, user["id"], cookies, {
        "capsule_type": "memory",
        "title": "Allergy Information",
        "content": "Allergic to penicillin.",
        "category": "health",
        "visibility": "internal",
        "emergency_accessible": True,
        "can_reshare": False,
        "network_ids": [],
    })
    await create_capsule(client, user["id"], cookies, {
        "capsule_type": "memory",
        "title": "Current Medications",
        "content": "Taking aspirin daily.",
        "category": "health",
        "visibility": "private",
        "emergency_accessible": False,
        "can_reshare": False,
        "network_ids": [],
    })

    # Also create a non-health capsule that should NOT appear in FHIR bundle
    await create_capsule(client, user["id"], cookies, {
        "capsule_type": "preference",
        "title": "Favorite Color",
        "content": "Blue",
        "category": "personal",
        "visibility": "private",
        "emergency_accessible": False,
        "can_reshare": False,
        "network_ids": [],
    })

    resp = await client.get(
        f"/api/users/{user['id']}/fhir/Bundle",
        cookies=cookies,
    )
    assert resp.status_code == 200
    bundle = resp.json()

    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    # Should have patient + 2 health resources
    assert bundle["total"] >= 3

    # Verify Patient resource is first
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"
    assert bundle["entry"][0]["resource"]["id"] == user["id"]

    # Check that health resources are included
    resource_types = [e["resource"]["resourceType"] for e in bundle["entry"][1:]]
    assert "AllergyIntolerance" in resource_types
    assert "MedicationStatement" in resource_types


@pytest.mark.asyncio
async def test_fhir_bundle_endpoint_empty(client):
    """GET /api/users/{user_id}/fhir/Bundle with no health capsules returns patient-only bundle."""
    user, cookies = await signup_user(client, VALID_USER)

    # Create only non-health capsule
    await create_capsule(client, user["id"], cookies, {
        "capsule_type": "preference",
        "title": "My Preferences",
        "content": "I like jazz music.",
        "category": "personal",
        "visibility": "private",
        "emergency_accessible": False,
        "can_reshare": False,
        "network_ids": [],
    })

    resp = await client.get(
        f"/api/users/{user['id']}/fhir/Bundle",
        cookies=cookies,
    )
    assert resp.status_code == 200
    bundle = resp.json()

    assert bundle["resourceType"] == "Bundle"
    # Only the Patient resource
    assert bundle["total"] == 1
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"


@pytest.mark.asyncio
async def test_fhir_bundle_endpoint_no_auth(anon_client, client):
    """GET /api/users/{user_id}/fhir/Bundle without auth returns 401."""
    user, _cookies = await signup_user(client, VALID_USER)

    resp = await anon_client.get(
        f"/api/users/{user['id']}/fhir/Bundle",
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_fhir_bundle_endpoint_wrong_user(client):
    """GET /api/users/{user_id}/fhir/Bundle as another user returns 403."""
    user_a, cookies_a = await signup_user(client, VALID_USER)
    _user_b, cookies_b = await signup_user(client, VALID_USER_B)

    # Create health capsule for user A
    await create_capsule(client, user_a["id"], cookies_a, {
        "capsule_type": "memory",
        "title": "Allergy Information",
        "content": "Allergic to peanuts.",
        "category": "health",
        "visibility": "private",
        "emergency_accessible": True,
        "can_reshare": False,
        "network_ids": [],
    })

    # User B tries to access user A's FHIR bundle
    resp = await client.get(
        f"/api/users/{user_a['id']}/fhir/Bundle",
        cookies=cookies_b,
    )
    assert resp.status_code == 403


# ===================================================================
# FHIR RESOURCE STRUCTURE VALIDATION
# ===================================================================


@pytest.mark.asyncio
async def test_fhir_allergy_has_required_fields():
    """AllergyIntolerance has all required FHIR R4 fields."""
    capsule = {
        "id": "cap-val-001",
        "title": "Allergy to Latex",
        "content": "Latex allergy confirmed by testing.",
        "category": "health",
        "visibility": "open",
        "emergency_accessible": True,
    }

    result = capsule_to_fhir(capsule, "p-001")

    # Required fields per FHIR R4 spec
    assert "resourceType" in result
    assert "id" in result
    assert "meta" in result
    assert "clinicalStatus" in result
    assert "verificationStatus" in result
    assert "patient" in result
    assert "code" in result


@pytest.mark.asyncio
async def test_fhir_medication_has_required_fields():
    """MedicationStatement has all required FHIR R4 fields."""
    capsule = {
        "id": "cap-val-002",
        "title": "Medications List",
        "content": "Metformin 1000mg daily.",
        "category": "health",
        "visibility": "internal",
        "emergency_accessible": False,
    }

    result = capsule_to_fhir(capsule, "p-002")

    assert "resourceType" in result
    assert "id" in result
    assert "status" in result
    assert "subject" in result
    assert "medicationCodeableConcept" in result


@pytest.mark.asyncio
async def test_fhir_condition_has_required_fields():
    """Condition has all required FHIR R4 fields."""
    capsule = {
        "id": "cap-val-003",
        "title": "Diabetes Diagnosis",
        "content": "Type 2 diabetes.",
        "category": "health",
        "visibility": "private",
        "emergency_accessible": True,
    }

    result = capsule_to_fhir(capsule, "p-003")

    assert "resourceType" in result
    assert "id" in result
    assert "clinicalStatus" in result
    assert "subject" in result
    assert "code" in result


@pytest.mark.asyncio
async def test_fhir_bundle_has_required_fields():
    """Bundle has all required FHIR R4 fields."""
    patient = {"resourceType": "Patient", "id": "p-004"}
    resources = [{"resourceType": "Observation", "id": "obs-001"}]

    bundle = build_bundle(patient, resources)

    assert "resourceType" in bundle
    assert "id" in bundle
    assert "meta" in bundle
    assert "type" in bundle
    assert "total" in bundle
    assert "entry" in bundle
    assert isinstance(bundle["entry"], list)


# ===================================================================
# EDGE CASE: allergic in content triggers AllergyIntolerance
# ===================================================================


@pytest.mark.asyncio
async def test_capsule_to_fhir_allergic_in_content():
    """Capsule with 'allergic' in content (not title) maps to AllergyIntolerance."""
    capsule = {
        "id": "cap-edge-001",
        "title": "Health Notes",
        "content": "Patient is allergic to bee stings. Carries EpiPen.",
        "category": "health",
        "visibility": "internal",
        "emergency_accessible": True,
    }

    result = capsule_to_fhir(capsule, "p-edge")

    assert result is not None
    assert result["resourceType"] == "AllergyIntolerance"
    assert "bee sting" in result["_trustmesh"]["substances"]


@pytest.mark.asyncio
async def test_capsule_to_fhir_emergency_contact():
    """Emergency contact capsule maps to FHIR RelatedPerson."""
    capsule = {
        "id": "cap-ec-001",
        "title": "Emergency Contact: Sarah Johnson",
        "content": "Wife, phone: 555-1234, relationship: spouse.",
        "category": "health",
        "visibility": "open",
        "emergency_accessible": True,
    }

    result = capsule_to_fhir(capsule, "p-ec")

    assert result is not None
    assert result["resourceType"] == "RelatedPerson"
    assert result["patient"]["reference"] == "Patient/p-ec"
    assert "Sarah Johnson" in result["name"][0]["text"]
