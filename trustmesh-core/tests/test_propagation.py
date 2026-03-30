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
