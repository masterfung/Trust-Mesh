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
