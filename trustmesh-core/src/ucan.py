"""UCAN (User Controlled Authorization Networks) token system.

Implements scoped, time-bounded authorization tokens for emergency access.
Tokens are signed with ed25519 keys and follow the UCAN spec:
  base64url(payload).base64url(signature)
"""

import base64
import hashlib
import json
import time
from dataclasses import dataclass

from src.crypto import sign_ed25519, verify_ed25519


# ── Role → Scope Mapping ──────────────────────────

ROLE_SCOPES: dict[str, dict] = {
    "attending_physician": {
        "categories": ["health"],
        "keywords": [
            "medication", "allergy", "condition", "surgery", "prescription",
            "emergency_contact", "medical", "blood_type", "weight", "height",
            "dnr", "insurance", "doctor", "hospital",
        ],
    },
    "er_nurse": {
        "categories": ["health"],
        "keywords": [
            "blood_type", "weight", "height", "allergy",
            "emergency_contact", "medical", "dnr",
        ],
    },
    "paramedic": {
        "categories": ["health"],
        "keywords": [
            "blood_type", "allergy", "dnr", "emergency_contact", "medical",
        ],
    },
    "admin": {
        "categories": ["health", "personal"],
        "keywords": [
            "insurance", "emergency_contact", "next_of_kin", "medical",
        ],
    },
}


@dataclass
class UCANPayload:
    iss: str        # issuer DID
    aud: str        # audience DID (patient's agent)
    att: dict       # attenuation: role + scope
    exp: int        # expiry (unix timestamp)
    iat: int        # issued at
    fct: dict       # facts/metadata


@dataclass
class UCANValidationResult:
    valid: bool
    payload: UCANPayload | None = None
    error: str | None = None


def _b64url_encode(data: bytes) -> str:
    """URL-safe base64 encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """URL-safe base64 decode with padding restoration."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_ucan_token(
    issuer_did: str,
    issuer_private_key: bytes,
    audience_did: str,
    role: str,
    duration_seconds: int = 3600,
    facts: dict | None = None,
) -> str:
    """Create a signed UCAN token.

    Args:
        issuer_did: DID of the issuing entity (e.g., hospital)
        issuer_private_key: Raw ed25519 private key bytes
        audience_did: DID of the target agent (patient's agent)
        role: Role from ROLE_SCOPES (e.g., "attending_physician")
        duration_seconds: Token validity duration
        facts: Additional metadata (practitioner name, NPI, case ID, reason)

    Returns:
        Token string: base64url(payload).base64url(signature)
    """
    if role not in ROLE_SCOPES:
        raise ValueError(f"Unknown role: {role}. Valid roles: {list(ROLE_SCOPES.keys())}")

    now = int(time.time())
    scope = ROLE_SCOPES[role]

    payload = {
        "iss": issuer_did,
        "aud": audience_did,
        "att": {
            "role": role,
            "scope": scope,
        },
        "exp": now + duration_seconds,
        "iat": now,
        "fct": facts or {},
    }

    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)

    signature = sign_ed25519(payload_bytes, issuer_private_key)
    signature_b64 = _b64url_encode(signature)

    return f"{payload_b64}.{signature_b64}"


def validate_ucan_token(
    token: str,
    expected_audience_did: str,
    issuer_public_key: bytes,
) -> UCANValidationResult:
    """Validate a UCAN token.

    Checks:
    1. Token format (payload.signature)
    2. Signature verification against issuer's public key
    3. Expiry
    4. Audience matches expected

    Returns UCANValidationResult with valid=True/False and parsed payload or error.
    """
    # Parse token
    parts = token.split(".")
    if len(parts) != 2:
        return UCANValidationResult(valid=False, error="Invalid token format: expected payload.signature")

    payload_b64, signature_b64 = parts

    try:
        payload_bytes = _b64url_decode(payload_b64)
        signature = _b64url_decode(signature_b64)
    except Exception:
        return UCANValidationResult(valid=False, error="Invalid base64 encoding")

    # Verify signature
    if not verify_ed25519(payload_bytes, signature, issuer_public_key):
        return UCANValidationResult(valid=False, error="Invalid signature")

    # Parse payload
    try:
        data = json.loads(payload_bytes)
    except json.JSONDecodeError:
        return UCANValidationResult(valid=False, error="Invalid payload JSON")

    payload = UCANPayload(
        iss=data.get("iss", ""),
        aud=data.get("aud", ""),
        att=data.get("att", {}),
        exp=data.get("exp", 0),
        iat=data.get("iat", 0),
        fct=data.get("fct", {}),
    )

    # Check expiry
    if payload.exp < int(time.time()):
        return UCANValidationResult(valid=False, payload=payload, error="Token expired")

    # Check audience
    if payload.aud != expected_audience_did:
        return UCANValidationResult(valid=False, payload=payload, error="Audience mismatch")

    # Check role is valid
    role = payload.att.get("role")
    if role not in ROLE_SCOPES:
        return UCANValidationResult(valid=False, payload=payload, error=f"Unknown role: {role}")

    return UCANValidationResult(valid=True, payload=payload)


def capsule_matches_scope(capsule_dict: dict, role: str) -> bool:
    """Check if a capsule matches the scope allowed by a role.

    A capsule matches if:
    - Its category is in the role's allowed categories, OR
    - Its title or content contains any of the role's keywords (word-boundary match)
    """
    import re

    if role not in ROLE_SCOPES:
        return False

    scope = ROLE_SCOPES[role]
    allowed_categories = scope["categories"]
    keywords = scope["keywords"]

    # Check category match
    capsule_category = capsule_dict.get("category", "").lower()
    if capsule_category and capsule_category in allowed_categories:
        return True

    # Check keyword match in title and content using word boundaries
    title = capsule_dict.get("title", "").lower()
    content = capsule_dict.get("content", "").lower()
    combined = f"{title} {content}"

    # Use word-boundary regex to avoid substring false positives
    # e.g., "doctor" should not match "doctored"
    return any(re.search(rf"\b{re.escape(kw)}\b", combined) for kw in keywords)


def token_hash(token: str) -> str:
    """Hash a token for audit logging (don't store raw tokens)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def is_token_revoked(db, token: str) -> bool:
    """Check if a UCAN token has been revoked."""
    from sqlalchemy import select
    from src.models import UCANRevocation

    t_hash = token_hash(token)
    result = await db.execute(
        select(UCANRevocation.id).where(UCANRevocation.token_hash == t_hash).limit(1)
    )
    return result.scalar_one_or_none() is not None
