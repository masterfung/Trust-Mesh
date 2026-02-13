"""Tests for UCAN token system — creation, validation, scope matching."""

import time

import pytest

from src.crypto import generate_ed25519_keypair, public_key_to_did, sign_ed25519, verify_ed25519
from src.ucan import (
    ROLE_SCOPES,
    UCANValidationResult,
    capsule_matches_scope,
    create_ucan_token,
    token_hash,
    validate_ucan_token,
)


@pytest.fixture
def issuer_keys():
    private_key, public_key = generate_ed25519_keypair()
    did = public_key_to_did(public_key)
    return private_key, public_key, did


@pytest.fixture
def audience_keys():
    private_key, public_key = generate_ed25519_keypair()
    did = public_key_to_did(public_key)
    return private_key, public_key, did


class TestEd25519:
    def test_keypair_generation(self):
        priv, pub = generate_ed25519_keypair()
        assert len(priv) == 32
        assert len(pub) == 32
        assert priv != pub

    def test_sign_and_verify(self):
        priv, pub = generate_ed25519_keypair()
        message = b"hello world"
        sig = sign_ed25519(message, priv)
        assert verify_ed25519(message, sig, pub)

    def test_verify_fails_with_wrong_key(self):
        priv1, pub1 = generate_ed25519_keypair()
        _, pub2 = generate_ed25519_keypair()
        message = b"hello world"
        sig = sign_ed25519(message, priv1)
        assert not verify_ed25519(message, sig, pub2)

    def test_verify_fails_with_tampered_message(self):
        priv, pub = generate_ed25519_keypair()
        sig = sign_ed25519(b"original", priv)
        assert not verify_ed25519(b"tampered", sig, pub)

    def test_did_format(self):
        _, pub = generate_ed25519_keypair()
        did = public_key_to_did(pub)
        assert did.startswith("did:key:z")
        assert len(did) > 20


class TestUCANCreate:
    def test_create_token(self, issuer_keys, audience_keys):
        priv, _, issuer_did = issuer_keys
        _, _, audience_did = audience_keys

        token = create_ucan_token(
            issuer_did=issuer_did,
            issuer_private_key=priv,
            audience_did=audience_did,
            role="attending_physician",
        )

        assert "." in token
        parts = token.split(".")
        assert len(parts) == 2

    def test_create_token_invalid_role(self, issuer_keys, audience_keys):
        priv, _, issuer_did = issuer_keys
        _, _, audience_did = audience_keys

        with pytest.raises(ValueError, match="Unknown role"):
            create_ucan_token(
                issuer_did=issuer_did,
                issuer_private_key=priv,
                audience_did=audience_did,
                role="nonexistent_role",
            )

    def test_create_with_facts(self, issuer_keys, audience_keys):
        priv, _, issuer_did = issuer_keys
        _, _, audience_did = audience_keys

        token = create_ucan_token(
            issuer_did=issuer_did,
            issuer_private_key=priv,
            audience_did=audience_did,
            role="er_nurse",
            facts={"practitioner_name": "Dr. Lee", "npi": "1234567890"},
        )

        assert len(token) > 50


class TestUCANValidate:
    def test_valid_token(self, issuer_keys, audience_keys):
        priv, pub, issuer_did = issuer_keys
        _, _, audience_did = audience_keys

        token = create_ucan_token(
            issuer_did=issuer_did,
            issuer_private_key=priv,
            audience_did=audience_did,
            role="attending_physician",
        )

        result = validate_ucan_token(token, audience_did, pub)
        assert result.valid
        assert result.payload is not None
        assert result.payload.iss == issuer_did
        assert result.payload.aud == audience_did
        assert result.payload.att["role"] == "attending_physician"

    def test_expired_token(self, issuer_keys, audience_keys):
        priv, pub, issuer_did = issuer_keys
        _, _, audience_did = audience_keys

        token = create_ucan_token(
            issuer_did=issuer_did,
            issuer_private_key=priv,
            audience_did=audience_did,
            role="attending_physician",
            duration_seconds=-1,  # Already expired
        )

        result = validate_ucan_token(token, audience_did, pub)
        assert not result.valid
        assert result.error == "Token expired"

    def test_wrong_audience(self, issuer_keys, audience_keys):
        priv, pub, issuer_did = issuer_keys
        _, _, audience_did = audience_keys

        token = create_ucan_token(
            issuer_did=issuer_did,
            issuer_private_key=priv,
            audience_did=audience_did,
            role="attending_physician",
        )

        result = validate_ucan_token(token, "did:key:zWRONG", pub)
        assert not result.valid
        assert result.error == "Audience mismatch"

    def test_tampered_token(self, issuer_keys, audience_keys):
        priv, pub, issuer_did = issuer_keys
        _, _, audience_did = audience_keys

        token = create_ucan_token(
            issuer_did=issuer_did,
            issuer_private_key=priv,
            audience_did=audience_did,
            role="attending_physician",
        )

        # Tamper with the payload
        parts = token.split(".")
        tampered = parts[0][:-3] + "XXX"
        tampered_token = f"{tampered}.{parts[1]}"

        result = validate_ucan_token(tampered_token, audience_did, pub)
        assert not result.valid
        assert "signature" in result.error.lower() or "base64" in result.error.lower()

    def test_wrong_issuer_key(self, issuer_keys, audience_keys):
        priv, _, issuer_did = issuer_keys
        _, _, audience_did = audience_keys

        token = create_ucan_token(
            issuer_did=issuer_did,
            issuer_private_key=priv,
            audience_did=audience_did,
            role="attending_physician",
        )

        # Verify with a different public key
        _, wrong_pub = generate_ed25519_keypair()
        result = validate_ucan_token(token, audience_did, wrong_pub)
        assert not result.valid
        assert "signature" in result.error.lower()

    def test_invalid_format(self, audience_keys):
        _, pub, audience_did = audience_keys
        result = validate_ucan_token("not-a-token", audience_did, pub)
        assert not result.valid
        assert "format" in result.error.lower()


class TestScopeMatching:
    def test_attending_physician_matches_health(self):
        capsule = {
            "category": "health",
            "title": "Blood Type",
            "content": "O+",
        }
        assert capsule_matches_scope(capsule, "attending_physician")

    def test_attending_physician_matches_keyword(self):
        capsule = {
            "category": "",
            "title": "Medical Info",
            "content": "Current medication: Atorvastatin 20mg",
        }
        assert capsule_matches_scope(capsule, "attending_physician")

    def test_paramedic_limited_scope(self):
        capsule = {
            "category": "",
            "title": "Insurance Info",
            "content": "Blue Cross PPO Member ID: BCX-447281",
        }
        # Paramedics don't have "insurance" in their keywords
        assert not capsule_matches_scope(capsule, "paramedic")

    def test_admin_matches_insurance(self):
        capsule = {
            "category": "",
            "title": "Insurance Info",
            "content": "Insurance: Blue Cross PPO Member ID: BCX-447281",
        }
        assert capsule_matches_scope(capsule, "admin")

    def test_no_match_for_non_medical(self):
        capsule = {
            "category": "",
            "title": "Guitar Practice Schedule",
            "content": "Practice in the garage weekday evenings",
        }
        assert not capsule_matches_scope(capsule, "attending_physician")
        assert not capsule_matches_scope(capsule, "er_nurse")
        assert not capsule_matches_scope(capsule, "paramedic")

    def test_er_nurse_matches_allergy(self):
        capsule = {
            "category": "health",
            "title": "Bill's Allergies",
            "content": "Peanut allergy (anaphylaxis)",
        }
        assert capsule_matches_scope(capsule, "er_nurse")

    def test_unknown_role(self):
        capsule = {"category": "health", "title": "test", "content": "test"}
        assert not capsule_matches_scope(capsule, "nonexistent_role")


class TestTokenHash:
    def test_hash_is_deterministic(self):
        h1 = token_hash("some-token")
        h2 = token_hash("some-token")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_different_tokens_different_hashes(self):
        h1 = token_hash("token-1")
        h2 = token_hash("token-2")
        assert h1 != h2
