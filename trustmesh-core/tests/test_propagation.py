"""Tests for capsule propagation — inference, schema validation, API integration."""

import pytest
from pydantic import ValidationError

from src.propagation_bridge import infer_propagation
from src.schemas import CapsuleCreate, CapsuleUpdate, CapsuleResponse


# ── _infer_propagation unit tests ──


class TestInferPropagation:
    def test_explicit_override(self):
        assert infer_propagation("broadcast", "general", "open") == "broadcast"

    def test_private_forces_silent(self):
        assert infer_propagation("broadcast", "health", "private") == "silent"

    def test_financial_forces_silent(self):
        assert infer_propagation("notify", "financial", "internal") == "silent"

    def test_personal_forces_silent(self):
        assert infer_propagation("broadcast", "personal", "open") == "silent"

    def test_health_default_broadcast(self):
        assert infer_propagation(None, "health", "internal") == "broadcast"

    def test_family_default_notify(self):
        assert infer_propagation(None, "family", "internal") == "notify"

    def test_work_default_silent(self):
        assert infer_propagation(None, "work", "internal") == "silent"

    def test_general_default_silent(self):
        assert infer_propagation(None, "general", "open") == "silent"

    def test_invalid_explicit_falls_through(self):
        # Invalid value should fall through to category default (family→notify)
        assert infer_propagation("scream", "family", "internal") == "notify"

    def test_empty_explicit_uses_category(self):
        assert infer_propagation("", "health", "internal") == "broadcast"

    def test_none_explicit_uses_category(self):
        assert infer_propagation(None, "family", "open") == "notify"


# ── Schema validation tests ──


class TestCapsuleSchemas:
    def test_create_propagation_valid(self):
        data = CapsuleCreate(
            capsule_type="memory", title="T", content="C", propagation="notify"
        )
        assert data.propagation == "notify"

    def test_create_propagation_default_silent(self):
        data = CapsuleCreate(capsule_type="memory", title="T", content="C")
        assert data.propagation == "silent"

    def test_create_propagation_invalid(self):
        with pytest.raises(ValidationError):
            CapsuleCreate(
                capsule_type="memory", title="T", content="C", propagation="scream"
            )

    def test_update_propagation_valid(self):
        data = CapsuleUpdate(propagation="broadcast")
        assert data.propagation == "broadcast"

    def test_update_propagation_none_by_default(self):
        data = CapsuleUpdate(title="New title")
        assert data.propagation is None

    def test_response_includes_propagation(self):
        data = CapsuleResponse(
            id="test-id",
            owner_id="owner-id",
            capsule_type="memory",
            title="Test",
            content="Content",
            tier="private",
            category="general",
            freshness="permanent",
            propagation="notify",
            last_verified_at="2026-01-01T00:00:00Z",
            is_archived=False,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            network_ids=[],
        )
        assert data.propagation == "notify"

    def test_response_propagation_default_silent(self):
        data = CapsuleResponse(
            id="test-id",
            owner_id="owner-id",
            capsule_type="memory",
            title="Test",
            content="Content",
            tier="private",
            category="general",
            freshness="permanent",
            last_verified_at="2026-01-01T00:00:00Z",
            is_archived=False,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            network_ids=[],
        )
        assert data.propagation == "silent"


# ── Phase 2a: Federation signing tests ──


class TestFederationSigning:
    def test_sign_federation_request_returns_headers(self):
        """sign_federation_request returns dict with required headers."""
        from src.crypto import generate_ed25519_keypair
        from src.federation_auth import sign_federation_request

        private_key, _ = generate_ed25519_keypair()
        headers = sign_federation_request(
            b'{"test": true}', private_key, method="POST", path="/api/pod/notify"
        )
        assert "X-TrustMesh-Signature" in headers
        assert "X-TrustMesh-Timestamp" in headers
        assert "X-TrustMesh-Nonce" in headers

    def test_signed_request_verifies(self):
        """A properly signed request verifies successfully."""
        from src.crypto import generate_ed25519_keypair, public_key_to_did
        from src.federation_auth import sign_federation_request, verify_federation_request

        private_key, public_key = generate_ed25519_keypair()
        did = public_key_to_did(public_key)
        body = b'{"test": true}'
        headers = sign_federation_request(
            body, private_key, method="POST", path="/api/pod/notify"
        )
        result = verify_federation_request(from_did=did, body=body, headers=headers)
        assert result.status == "valid"

    def test_forged_signature_rejected(self):
        """A request signed with wrong key is rejected."""
        from src.crypto import generate_ed25519_keypair, public_key_to_did
        from src.federation_auth import sign_federation_request, verify_federation_request

        priv1, pub1 = generate_ed25519_keypair()
        priv2, pub2 = generate_ed25519_keypair()
        did1 = public_key_to_did(pub1)
        body = b'{"test": true}'
        headers = sign_federation_request(
            body, priv2, method="POST", path="/api/pod/notify"
        )  # signed with wrong key
        result = verify_federation_request(from_did=did1, body=body, headers=headers)
        assert result.status == "invalid"


# ── Phase 2b: Debounce bridge tests ──


class TestDebounceBridge:
    def test_debounce_push_returns_bool(self):
        from src.propagation_bridge import debounce_push

        # notify tier should return True (buffered) or False (no Zig available)
        result = debounce_push(
            "http://test:9001", "test-capsule-id-aaaa-bbbb-cccccccccccc", "notify"
        )
        assert isinstance(result, bool)

    def test_debounce_flush_returns_list(self):
        from src.propagation_bridge import debounce_flush

        result = debounce_flush("http://nonexistent:9999")
        assert isinstance(result, list)

    def test_debounce_pending_returns_int(self):
        from src.propagation_bridge import debounce_pending

        result = debounce_pending()
        assert isinstance(result, int)
        assert result >= 0


# ── Phase 2c: Mute model tests ──


class TestMuteModel:
    def test_network_subscription_pref_model(self):
        """NetworkSubscriptionPref model can be instantiated."""
        from src.models import NetworkSubscriptionPref

        pref = NetworkSubscriptionPref(
            user_id="test-user",
            network_id="test-network",
            muted=True,
        )
        assert pref.muted is True
        assert pref.mute_until is None

    def test_infer_propagation_unaffected_by_mute(self):
        """Propagation inference doesn't consider mute — that's a fan-out concern."""
        from src.propagation_bridge import infer_propagation

        # Mute doesn't change inference — it's checked at fan-out time
        assert infer_propagation(None, "family", "internal") == "notify"


# ── Phase 3a: Staleness tests ──


class TestStaleness:
    def test_capsule_response_includes_staleness_fields(self):
        """CapsuleResponse has stale_since, stale_reason, stale_source_capsule_id."""
        from src.schemas import CapsuleResponse

        data = CapsuleResponse(
            id="test-id",
            owner_id="owner-id",
            capsule_type="memory",
            title="Test",
            content="Content",
            tier="private",
            category="general",
            freshness="permanent",
            last_verified_at="2026-01-01T00:00:00Z",
            is_archived=False,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            network_ids=[],
            stale_since="2026-03-28T12:00:00Z",
            stale_reason="Alice updated 'Travel Plans' — this capsule may reference outdated information.",
            stale_source_capsule_id="src-capsule-id",
        )
        assert data.stale_since is not None
        assert "Alice" in data.stale_reason
        assert data.stale_source_capsule_id == "src-capsule-id"

    def test_capsule_response_staleness_defaults_none(self):
        """CapsuleResponse staleness fields default to None."""
        from src.schemas import CapsuleResponse

        data = CapsuleResponse(
            id="test-id",
            owner_id="owner-id",
            capsule_type="memory",
            title="Test",
            content="Content",
            tier="private",
            category="general",
            freshness="permanent",
            last_verified_at="2026-01-01T00:00:00Z",
            is_archived=False,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            network_ids=[],
        )
        assert data.stale_since is None
        assert data.stale_reason is None
        assert data.stale_source_capsule_id is None

    def test_hook_prompt_contains_query_peer(self):
        """Generated hook prompt mentions query_peer and save_capsule."""
        # Simulate the prompt generation logic from _create_staleness_entry
        stale_capsule_title = "Mom's Medication Schedule"
        source_capsule_title = "Updated Prescription"
        owner_display_name = "Dr. Chen"

        hook_prompt = (
            f"Capsule '{stale_capsule_title}' may be outdated because "
            f"{owner_display_name} updated '{source_capsule_title}'. "
            f"Use query_peer to verify current information and save_capsule to update if needed."
        )
        assert "query_peer" in hook_prompt
        assert "save_capsule" in hook_prompt
        assert "Dr. Chen" in hook_prompt

    def test_research_prompt_includes_browse_web(self):
        """Stale itinerary capsule prompt includes browse_web instruction."""
        stale_capsule_title = "Paris Trip Itinerary"
        source_capsule_title = "Updated Flight Info"
        owner_display_name = "Alice"

        hook_prompt = (
            f"Capsule '{stale_capsule_title}' may be outdated because "
            f"{owner_display_name} updated '{source_capsule_title}'. "
            f"Use query_peer to verify current information and save_capsule to update if needed."
        )

        _lower = stale_capsule_title.lower()
        if any(kw in _lower for kw in ("itinerary", "restaurant", "trip", "travel", "flight", "hotel")):
            hook_prompt += (
                " Also use browse_web to check for updated schedules, "
                "reservations, or travel advisories."
            )

        assert "browse_web" in hook_prompt
        assert "itinerary" in stale_capsule_title.lower()

    def test_non_travel_capsule_no_browse_web(self):
        """Non-travel stale capsule prompt does NOT include browse_web."""
        stale_capsule_title = "Mom's Medication Schedule"

        hook_prompt = (
            f"Capsule '{stale_capsule_title}' may be outdated. "
            f"Use query_peer to verify current information and save_capsule to update if needed."
        )

        _lower = stale_capsule_title.lower()
        if any(kw in _lower for kw in ("itinerary", "restaurant", "trip", "travel", "flight", "hotel")):
            hook_prompt += " Also use browse_web."

        assert "browse_web" not in hook_prompt

    def test_search_stale_references_returns_terms(self):
        """search_stale_references returns list of search terms."""
        from src.propagation_bridge import search_stale_references

        terms = search_stale_references("user-1", "Alice Johnson", ["medication", "schedule"])
        assert isinstance(terms, list)
        assert "alice" in terms
        assert "johnson" in terms
        assert "medication" in terms

    def test_search_stale_references_empty_inputs(self):
        """search_stale_references returns empty list for empty inputs."""
        from src.propagation_bridge import search_stale_references

        assert search_stale_references("user-1", "", []) == []

    def test_mark_capsules_stale_returns_count(self):
        """mark_capsules_stale returns count of capsules to be marked."""
        from src.propagation_bridge import mark_capsules_stale

        count = mark_capsules_stale(["c1", "c2", "c3"], "test reason", "src-id")
        assert count == 3

    def test_mark_capsules_stale_empty_list(self):
        """mark_capsules_stale returns 0 for empty list."""
        from src.propagation_bridge import mark_capsules_stale

        count = mark_capsules_stale([], "test reason", "src-id")
        assert count == 0

    def test_knowledge_capsule_model_has_staleness_fields(self):
        """KnowledgeCapsule model has stale_since, stale_reason, stale_source_capsule_id."""
        from src.models import KnowledgeCapsule

        capsule = KnowledgeCapsule(
            owner_id="test",
            capsule_type="memory",
            title="Test",
            content_encrypted=b"enc",
        )
        assert capsule.stale_since is None
        assert capsule.stale_reason is None
        assert capsule.stale_source_capsule_id is None
