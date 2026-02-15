"""Comprehensive Pydantic schema validation tests for TrustMesh.

These are pure unit tests that validate Pydantic model constraints directly
without requiring a database or running server.
"""

import pytest
from pydantic import ValidationError

from src.schemas import (
    CapsuleCreate,
    CapsuleUpdate,
    ConnectionRequestCreate,
    ConnectionRequestUpdate,
    ContextSwitch,
    ConversationMessage,
    EmergencyAccessRequest,
    EmergencyTokenRequest,
    LoginRequest,
    NetworkCreate,
    NetworkJoinRequestCreate,
    NetworkJoinRequestUpdate,
    QueryCreate,
    UserCreate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_PASSWORD = "SecureP@ssword1!"  # 16 chars, upper, lower, digit, special


def _make_user(**overrides) -> dict:
    """Return a valid UserCreate dict, with optional overrides."""
    base = {
        "username": "testuser",
        "display_name": "Test User",
        "bio": "A short bio.",
        "password": VALID_PASSWORD,
    }
    base.update(overrides)
    return base


def _make_capsule(**overrides) -> dict:
    """Return a valid CapsuleCreate dict, with optional overrides."""
    base = {
        "capsule_type": "memory",
        "title": "My First Capsule",
        "content": "Some knowledge content here.",
        "tier": "private",
        "category": "general",
    }
    base.update(overrides)
    return base


def _make_query(**overrides) -> dict:
    """Return a valid QueryCreate dict, with optional overrides."""
    base = {
        "from_user_id": "user-aaa",
        "to_user_id": "user-bbb",
        "question": "What is the meaning of life?",
    }
    base.update(overrides)
    return base


# ===================================================================
# UserCreate tests
# ===================================================================


class TestUserCreate:
    """Validation tests for the UserCreate schema."""

    def test_valid_user_accepted(self):
        """1. A fully-valid payload should be accepted."""
        user = UserCreate(**_make_user())
        assert user.username == "testuser"
        assert user.display_name == "Test User"

    def test_username_too_short(self):
        """2. Username shorter than 2 characters must be rejected."""
        with pytest.raises(ValidationError):
            UserCreate(**_make_user(username="a"))

    def test_username_too_long(self):
        """3. Username longer than 50 characters must be rejected."""
        with pytest.raises(ValidationError):
            UserCreate(**_make_user(username="x" * 51))

    def test_bio_too_long(self):
        """4. Bio longer than 5000 characters must be rejected."""
        with pytest.raises(ValidationError):
            UserCreate(**_make_user(bio="x" * 5001))

    def test_password_too_short(self):
        """5. Password shorter than 16 characters must be rejected."""
        with pytest.raises(ValidationError):
            UserCreate(**_make_user(password="Sh0rt!pass"))

    def test_password_no_uppercase(self):
        """6. Password without uppercase letter must be rejected."""
        with pytest.raises(ValidationError):
            UserCreate(**_make_user(password="alllowercase1234!"))

    def test_password_no_lowercase(self):
        """7. Password without lowercase letter must be rejected."""
        with pytest.raises(ValidationError):
            UserCreate(**_make_user(password="ALLUPPERCASE1234!"))

    def test_password_no_digit(self):
        """8. Password without a digit must be rejected."""
        with pytest.raises(ValidationError):
            UserCreate(**_make_user(password="NoDigitsHere!@#$%"))

    def test_password_no_special_char(self):
        """9. Password without a special character must be rejected."""
        with pytest.raises(ValidationError):
            UserCreate(**_make_user(password="NoSpecialChars12345"))


# ===================================================================
# CapsuleCreate tests
# ===================================================================


class TestCapsuleCreate:
    """Validation tests for the CapsuleCreate schema."""

    def test_valid_capsule_accepted(self):
        """10. A fully-valid capsule payload should be accepted."""
        capsule = CapsuleCreate(**_make_capsule())
        assert capsule.title == "My First Capsule"
        assert capsule.capsule_type == "memory"

    def test_empty_title(self):
        """11. Empty title must be rejected (min_length=1)."""
        with pytest.raises(ValidationError):
            CapsuleCreate(**_make_capsule(title=""))

    def test_title_too_long(self):
        """12. Title longer than 200 characters must be rejected."""
        with pytest.raises(ValidationError):
            CapsuleCreate(**_make_capsule(title="x" * 201))

    def test_content_too_long(self):
        """13. Content longer than 100 000 characters must be rejected."""
        with pytest.raises(ValidationError):
            CapsuleCreate(**_make_capsule(content="x" * 100_001))

    def test_invalid_capsule_type(self):
        """14. Invalid capsule_type must be rejected."""
        with pytest.raises(ValidationError):
            CapsuleCreate(**_make_capsule(capsule_type="diary"))

    def test_invalid_tier(self):
        """15. Invalid tier must be rejected."""
        with pytest.raises(ValidationError):
            CapsuleCreate(**_make_capsule(tier="secret"))

    def test_category_too_long(self):
        """16. Category longer than 100 characters must be rejected."""
        with pytest.raises(ValidationError):
            CapsuleCreate(**_make_capsule(category="c" * 101))


# ===================================================================
# QueryCreate tests
# ===================================================================


class TestQueryCreate:
    """Validation tests for the QueryCreate schema."""

    def test_valid_query_accepted(self):
        """17. A fully-valid query payload should be accepted."""
        query = QueryCreate(**_make_query())
        assert query.question == "What is the meaning of life?"

    def test_question_too_long(self):
        """18. Question longer than 10 000 characters must be rejected."""
        with pytest.raises(ValidationError):
            QueryCreate(**_make_query(question="q" * 10_001))

    def test_empty_question(self):
        """19. Empty question must be rejected (min_length=1)."""
        with pytest.raises(ValidationError):
            QueryCreate(**_make_query(question=""))


# ===================================================================
# ConversationMessage tests
# ===================================================================


class TestConversationMessage:
    """Validation tests for the ConversationMessage schema."""

    def test_valid_message_accepted(self):
        """20. A valid conversation message should be accepted."""
        msg = ConversationMessage(role="user", content="Hello there!")
        assert msg.role == "user"
        assert msg.content == "Hello there!"

    def test_invalid_role(self):
        """21. Role that is neither 'user' nor 'assistant' must be rejected."""
        with pytest.raises(ValidationError):
            ConversationMessage(role="system", content="Hello")

    def test_content_too_long(self):
        """22. Content longer than 50 000 characters must be rejected."""
        with pytest.raises(ValidationError):
            ConversationMessage(role="user", content="x" * 50_001)


# ===================================================================
# ConnectionRequestCreate tests
# ===================================================================


class TestConnectionRequestCreate:
    """Validation tests for the ConnectionRequestCreate schema."""

    def test_message_too_long(self):
        """23. Message longer than 500 characters must be rejected."""
        with pytest.raises(ValidationError):
            ConnectionRequestCreate(
                from_user_id="u1",
                to_user_id="u2",
                message="m" * 501,
            )


# ===================================================================
# NetworkCreate tests
# ===================================================================


class TestNetworkCreate:
    """Validation tests for the NetworkCreate schema."""

    def test_valid_network_accepted(self):
        """24. A fully-valid network payload should be accepted."""
        net = NetworkCreate(name="My Network", owner_id="owner-1")
        assert net.name == "My Network"
        assert net.description == ""

    def test_empty_name(self):
        """25. Empty name must be rejected (min_length=1)."""
        with pytest.raises(ValidationError):
            NetworkCreate(name="", owner_id="owner-1")

    def test_name_too_long(self):
        """26. Name longer than 100 characters must be rejected."""
        with pytest.raises(ValidationError):
            NetworkCreate(name="n" * 101, owner_id="owner-1")

    def test_description_too_long(self):
        """27. Description longer than 2000 characters must be rejected."""
        with pytest.raises(ValidationError):
            NetworkCreate(
                name="Net",
                owner_id="owner-1",
                description="d" * 2001,
            )


# ===================================================================
# NetworkJoinRequestCreate tests
# ===================================================================


class TestNetworkJoinRequestCreate:
    """Validation tests for the NetworkJoinRequestCreate schema."""

    def test_message_too_long(self):
        """28. Message longer than 500 characters must be rejected."""
        with pytest.raises(ValidationError):
            NetworkJoinRequestCreate(message="m" * 501)


# ===================================================================
# ConnectionRequestUpdate tests
# ===================================================================


class TestConnectionRequestUpdate:
    """Validation tests for the ConnectionRequestUpdate schema."""

    def test_valid_accepted_status(self):
        """29. Status 'accepted' should be accepted."""
        update = ConnectionRequestUpdate(status="accepted")
        assert update.status == "accepted"

    def test_valid_declined_status(self):
        """30. Status 'declined' should be accepted."""
        update = ConnectionRequestUpdate(status="declined")
        assert update.status == "declined"

    def test_invalid_status(self):
        """31. Status 'maybe' must be rejected."""
        with pytest.raises(ValidationError):
            ConnectionRequestUpdate(status="maybe")


# ===================================================================
# NetworkJoinRequestUpdate tests
# ===================================================================


class TestNetworkJoinRequestUpdate:
    """Validation tests for the NetworkJoinRequestUpdate schema."""

    def test_valid_approved_status(self):
        """32. Status 'approved' should be accepted."""
        update = NetworkJoinRequestUpdate(status="approved")
        assert update.status == "approved"

    def test_invalid_rejected_status(self):
        """33. Status 'rejected' must be rejected (only 'approved'/'declined' allowed)."""
        with pytest.raises(ValidationError):
            NetworkJoinRequestUpdate(status="rejected")


# ===================================================================
# ContextSwitch tests
# ===================================================================


class TestContextSwitch:
    """Validation tests for the ContextSwitch schema."""

    def test_valid_work(self):
        """34. Context 'work' should be accepted."""
        cs = ContextSwitch(context="work")
        assert cs.context == "work"

    def test_valid_personal(self):
        """35. Context 'personal' should be accepted."""
        cs = ContextSwitch(context="personal")
        assert cs.context == "personal"

    def test_valid_all(self):
        """36. Context 'all' should be accepted."""
        cs = ContextSwitch(context="all")
        assert cs.context == "all"

    def test_invalid_context(self):
        """37. Context 'mixed' must be rejected."""
        with pytest.raises(ValidationError):
            ContextSwitch(context="mixed")


# ===================================================================
# EmergencyTokenRequest tests
# ===================================================================


class TestEmergencyTokenRequest:
    """Validation tests for the EmergencyTokenRequest schema."""

    def test_valid_attending_physician(self):
        """38. Valid request with attending_physician role should be accepted."""
        req = EmergencyTokenRequest(
            issuer_user_id="u1",
            patient_username="patient1",
            role="attending_physician",
            duration_seconds=1800,
            practitioner_name="Dr. Smith",
        )
        assert req.role == "attending_physician"

    def test_invalid_role(self):
        """39. Role 'doctor' must be rejected."""
        with pytest.raises(ValidationError):
            EmergencyTokenRequest(
                issuer_user_id="u1",
                patient_username="patient1",
                role="doctor",
            )

    def test_duration_too_long(self):
        """40. Duration exceeding 3600 seconds must be rejected."""
        with pytest.raises(ValidationError):
            EmergencyTokenRequest(
                issuer_user_id="u1",
                patient_username="patient1",
                role="er_nurse",
                duration_seconds=7200,
            )

    def test_practitioner_name_too_long(self):
        """41. Practitioner name longer than 200 characters must be rejected."""
        with pytest.raises(ValidationError):
            EmergencyTokenRequest(
                issuer_user_id="u1",
                patient_username="patient1",
                role="paramedic",
                practitioner_name="N" * 201,
            )


# ===================================================================
# EmergencyAccessRequest tests
# ===================================================================


class TestEmergencyAccessRequest:
    """Validation tests for the EmergencyAccessRequest schema."""

    def test_token_too_long(self):
        """42. Token longer than 4096 characters must be rejected."""
        with pytest.raises(ValidationError):
            EmergencyAccessRequest(
                token="t" * 4097,
                patient_username="patient1",
            )

    def test_patient_username_too_long(self):
        """43. Patient username longer than 50 characters must be rejected."""
        with pytest.raises(ValidationError):
            EmergencyAccessRequest(
                token="valid-token",
                patient_username="u" * 51,
            )


# ===================================================================
# LoginRequest tests
# ===================================================================


class TestLoginRequest:
    """Validation tests for the LoginRequest schema."""

    def test_username_too_long(self):
        """44. Username longer than 50 characters must be rejected."""
        with pytest.raises(ValidationError):
            LoginRequest(username="u" * 51, password="password")

    def test_password_too_long(self):
        """45. Password longer than 128 characters must be rejected."""
        with pytest.raises(ValidationError):
            LoginRequest(username="user", password="p" * 129)


# ===================================================================
# CapsuleUpdate tests
# ===================================================================


class TestCapsuleUpdate:
    """Validation tests for the CapsuleUpdate schema."""

    def test_valid_partial_update(self):
        """46. A valid partial update should be accepted."""
        update = CapsuleUpdate(title="New Title")
        assert update.title == "New Title"
        assert update.content is None
        assert update.capsule_type is None

    def test_title_too_long(self):
        """47. Title longer than 200 characters must be rejected."""
        with pytest.raises(ValidationError):
            CapsuleUpdate(title="x" * 201)

    def test_content_too_long(self):
        """48. Content longer than 100 000 characters must be rejected."""
        with pytest.raises(ValidationError):
            CapsuleUpdate(content="x" * 100_001)

    def test_invalid_capsule_type(self):
        """49. Invalid capsule_type must be rejected."""
        with pytest.raises(ValidationError):
            CapsuleUpdate(capsule_type="diary")

    def test_invalid_tier(self):
        """50. Invalid tier must be rejected."""
        with pytest.raises(ValidationError):
            CapsuleUpdate(tier="secret")


# ===================================================================
# Phase 2: Pool type + entity type validation tests
# ===================================================================


class TestUserTypeValidation:
    """Validation tests for entity type restrictions."""

    def test_user_type_person_accepted(self):
        """51. user_type 'person' should be accepted."""
        user = UserCreate(**_make_user(user_type="person"))
        assert user.user_type == "person"

    def test_user_type_organization_accepted(self):
        """52. user_type 'organization' should be accepted."""
        user = UserCreate(**_make_user(user_type="organization"))
        assert user.user_type == "organization"

    def test_user_type_government_accepted(self):
        """53. user_type 'government' should be accepted."""
        user = UserCreate(**_make_user(user_type="government"))
        assert user.user_type == "government"

    def test_user_type_invalid_rejected(self):
        """54. user_type 'robot' must be rejected."""
        with pytest.raises(ValidationError):
            UserCreate(**_make_user(user_type="robot"))

    def test_user_type_service_rejected(self):
        """55. user_type 'service' (old name) must be rejected."""
        with pytest.raises(ValidationError):
            UserCreate(**_make_user(user_type="service"))


class TestNetworkCreatePoolType:
    """Validation tests for pool_type and shared_categories on NetworkCreate."""

    def test_network_with_pool_type(self):
        """56. NetworkCreate with pool_type should be accepted."""
        net = NetworkCreate(
            name="Health Pool", owner_id="owner-1",
            pool_type="category_scoped", shared_categories=["health"],
        )
        assert net.pool_type == "category_scoped"
        assert net.shared_categories == ["health"]

    def test_network_default_pool_type(self):
        """57. NetworkCreate defaults to pool_type 'standard'."""
        net = NetworkCreate(name="Default Pool", owner_id="owner-1")
        assert net.pool_type == "standard"
        assert net.shared_categories is None

    def test_network_multiple_categories(self):
        """58. NetworkCreate with multiple shared_categories."""
        net = NetworkCreate(
            name="Multi Pool", owner_id="owner-1",
            pool_type="category_scoped", shared_categories=["health", "work", "family"],
        )
        assert len(net.shared_categories) == 3

    def test_network_public_registry_type(self):
        """59. NetworkCreate with public_registry pool_type."""
        net = NetworkCreate(
            name="Public Pool", owner_id="owner-1",
            pool_type="public_registry",
        )
        assert net.pool_type == "public_registry"
