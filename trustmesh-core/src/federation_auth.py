"""Federation request authentication helpers (signed requests + replay protection).

Design goals:
- Backward compatible: unsigned requests can still be treated as "public".
- Stronger trust elevation: elevated trust (ghost -> network) requires a valid signature.
- No per-peer key storage required: verify using did:key self-certifying public keys.

Signing scheme (Ed25519):
- Sender signs: "<timestamp>\\n<nonce>\\n" + raw request body bytes
- Headers:
  - X-TrustMesh-Timestamp: unix seconds (int)
  - X-TrustMesh-Nonce: random urlsafe token
  - X-TrustMesh-Signature: base64url(signature) without padding
  - X-TrustMesh-Signature-Alg: "ed25519" (optional; defaults to ed25519)

Replay protection:
- In-memory nonce cache with TTL. Best-effort for single-process deployments.
  For multi-worker/multi-instance, replace with Redis or shared store.
"""

from __future__ import annotations

import base64
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Literal

logger = logging.getLogger(__name__)

from src.crypto import did_key_to_public_key, sign_ed25519, verify_ed25519

HEADER_TIMESTAMP = "X-TrustMesh-Timestamp"
HEADER_NONCE = "X-TrustMesh-Nonce"
HEADER_SIGNATURE = "X-TrustMesh-Signature"
HEADER_SIGNATURE_ALG = "X-TrustMesh-Signature-Alg"

ALG_ED25519 = "ed25519"

# Default verification window and replay TTL (seconds).
DEFAULT_SKEW_SECONDS = 60
DEFAULT_NONCE_TTL_SECONDS = 120

# Keep nonce values small + predictable for header parsing.
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")

# (from_did, nonce) -> expires_at_epoch_seconds
_SEEN_NONCES: dict[tuple[str, str], int] = {}


@dataclass(frozen=True)
class FederationVerifyResult:
    status: Literal["missing", "valid", "invalid"]
    reason: str | None = None


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - (len(s) % 4)
    if padding != 4:
        s = s + ("=" * padding)
    return base64.urlsafe_b64decode(s)


def _now_epoch(now: datetime | None) -> int:
    if now is None:
        return int(time.time())
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return int(now.timestamp())


def _signed_message(ts: int, nonce: str, body: bytes, *, method: str = "", path: str = "") -> bytes:
    """Build the message to sign. Includes method+path when provided (new format)."""
    if method and path:
        return f"{method}\n{path}\n{ts}\n{nonce}\n".encode("utf-8") + body
    return f"{ts}\n{nonce}\n".encode("utf-8") + body


def _prune_seen_nonces(now_epoch: int) -> None:
    # Simple pruning: remove expired entries. Called opportunistically.
    if not _SEEN_NONCES:
        return
    expired = [k for k, exp in _SEEN_NONCES.items() if exp <= now_epoch]
    for k in expired:
        _SEEN_NONCES.pop(k, None)


def reset_federation_auth_state() -> None:
    """Test helper: clear in-memory replay cache."""
    _SEEN_NONCES.clear()


def sign_federation_request(
    body: bytes,
    private_key_bytes: bytes,
    *,
    method: str = "",
    path: str = "",
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Create signature headers for a federation request body."""
    ts = int(timestamp if timestamp is not None else time.time())
    n = nonce if nonce is not None else secrets.token_urlsafe(18)
    msg = _signed_message(ts, n, body, method=method, path=path)
    sig = sign_ed25519(msg, private_key_bytes)
    headers = {
        HEADER_TIMESTAMP: str(ts),
        HEADER_NONCE: n,
        HEADER_SIGNATURE: _b64url_encode(sig),
        HEADER_SIGNATURE_ALG: ALG_ED25519,
    }
    # Include method+path in headers so verifier can reconstruct
    if method and path:
        headers["X-TrustMesh-Method"] = method
        headers["X-TrustMesh-Path"] = path
    return headers


def verify_federation_request(
    *,
    from_did: str,
    body: bytes,
    headers: Mapping[str, str],
    now: datetime | None = None,
    max_skew_seconds: int = DEFAULT_SKEW_SECONDS,
    nonce_ttl_seconds: int = DEFAULT_NONCE_TTL_SECONDS,
) -> FederationVerifyResult:
    """Verify federation request signature + replay protection.

    Returns:
    - status="missing" if no signature headers present (backward compatible)
    - status="valid" if signature checks out and nonce isn't replayed
    - status="invalid" otherwise (reason explains why)
    """
    ts_s = headers.get(HEADER_TIMESTAMP)
    nonce = headers.get(HEADER_NONCE)
    sig_s = headers.get(HEADER_SIGNATURE)
    alg = (headers.get(HEADER_SIGNATURE_ALG) or ALG_ED25519).lower().strip()

    # Backward compatible: if caller did not include signature headers at all.
    if not ts_s and not nonce and not sig_s:
        return FederationVerifyResult(status="missing")

    # Partial headers are always invalid (prevents ambiguous behavior).
    if not ts_s:
        return FederationVerifyResult(status="invalid", reason=f"Missing {HEADER_TIMESTAMP}")
    if not nonce:
        return FederationVerifyResult(status="invalid", reason=f"Missing {HEADER_NONCE}")
    if not sig_s:
        return FederationVerifyResult(status="invalid", reason=f"Missing {HEADER_SIGNATURE}")
    if alg != ALG_ED25519:
        return FederationVerifyResult(status="invalid", reason=f"Unsupported signature alg: {alg}")

    try:
        ts = int(ts_s)
    except Exception:
        return FederationVerifyResult(status="invalid", reason="Invalid timestamp")

    if ts <= 0:
        return FederationVerifyResult(status="invalid", reason="Invalid timestamp")

    if not _NONCE_RE.match(nonce):
        return FederationVerifyResult(status="invalid", reason="Invalid nonce format")

    now_epoch = _now_epoch(now)
    if abs(now_epoch - ts) > max_skew_seconds:
        return FederationVerifyResult(status="invalid", reason="Timestamp outside allowed window")

    # Replay protection: reject re-used nonce within the TTL window.
    # We only record the nonce after signature verification succeeds to avoid
    # letting invalid requests fill the cache (best-effort DoS resistance).
    _prune_seen_nonces(now_epoch)
    key = (from_did, nonce)
    exp = _SEEN_NONCES.get(key)
    if exp is not None and exp > now_epoch:
        logger.warning(f"Federation replay detected: did={from_did[:20]}..., nonce={nonce[:16]}")
        return FederationVerifyResult(status="invalid", reason="Replay detected (nonce already used)")

    try:
        sig = _b64url_decode(sig_s)
    except Exception:
        return FederationVerifyResult(status="invalid", reason="Invalid signature encoding")
    if len(sig) != 64:
        return FederationVerifyResult(status="invalid", reason="Invalid signature length")

    try:
        pub = did_key_to_public_key(from_did)
    except Exception:
        return FederationVerifyResult(status="invalid", reason="Unsupported or invalid from_did (did:key required)")

    # Try new format first (with method+path), then fall back to old format
    req_method = headers.get("X-TrustMesh-Method", "")
    req_path = headers.get("X-TrustMesh-Path", "")

    if req_method and req_path:
        # New format: method+path included
        msg = _signed_message(ts, nonce, body, method=req_method, path=req_path)
        if not verify_ed25519(msg, sig, pub):
            logger.warning(f"Federation invalid signature: did={from_did[:20]}...")
            return FederationVerifyResult(status="invalid", reason="Invalid signature")
    else:
        # Legacy format: no method+path
        msg = _signed_message(ts, nonce, body)
        if not verify_ed25519(msg, sig, pub):
            logger.warning(f"Federation invalid signature: did={from_did[:20]}...")
            return FederationVerifyResult(status="invalid", reason="Invalid signature")

    _SEEN_NONCES[key] = now_epoch + int(nonce_ttl_seconds)

    # Opportunistic pruning if cache grows large (defense against memory growth).
    if len(_SEEN_NONCES) > 50_000:
        _prune_seen_nonces(now_epoch)

    return FederationVerifyResult(status="valid")


def verify_registry_response(
    *,
    registry_did: str,
    body: bytes,
    headers: Mapping[str, str],
    now: datetime | None = None,
    max_skew_seconds: int = DEFAULT_SKEW_SECONDS,
) -> FederationVerifyResult:
    """Verify a signed response from the TrustMesh registry.

    The registry signs responses with the same scheme as federation requests
    (timestamp + nonce + body), but as a *response* we skip replay protection
    (each response nonce is unique; we just check the timestamp window).

    registry_did: the expected did:key of the registry (from TRUSTMESH_REGISTRY_DID
                  or the X-TrustMesh-Registry-DID response header).

    Returns status="missing" if no signature headers are present (registry may be
    running without a keypair configured), "valid" / "invalid" otherwise.
    """
    ts_s = headers.get(HEADER_TIMESTAMP)
    nonce = headers.get(HEADER_NONCE)
    sig_s = headers.get(HEADER_SIGNATURE)
    alg = (headers.get(HEADER_SIGNATURE_ALG) or ALG_ED25519).lower().strip()

    if not ts_s and not nonce and not sig_s:
        return FederationVerifyResult(status="missing")

    if not ts_s:
        return FederationVerifyResult(status="invalid", reason=f"Missing {HEADER_TIMESTAMP}")
    if not nonce:
        return FederationVerifyResult(status="invalid", reason=f"Missing {HEADER_NONCE}")
    if not sig_s:
        return FederationVerifyResult(status="invalid", reason=f"Missing {HEADER_SIGNATURE}")
    if alg != ALG_ED25519:
        return FederationVerifyResult(status="invalid", reason=f"Unsupported alg: {alg}")

    try:
        ts = int(ts_s)
    except Exception:
        return FederationVerifyResult(status="invalid", reason="Invalid timestamp")

    now_epoch = _now_epoch(now)
    if abs(now_epoch - ts) > max_skew_seconds:
        return FederationVerifyResult(status="invalid", reason="Timestamp outside allowed window")

    try:
        sig = _b64url_decode(sig_s)
    except Exception:
        return FederationVerifyResult(status="invalid", reason="Invalid signature encoding")
    if len(sig) != 64:
        return FederationVerifyResult(status="invalid", reason="Invalid signature length")

    try:
        pub = did_key_to_public_key(registry_did)
    except Exception as e:
        return FederationVerifyResult(status="invalid", reason=f"Invalid registry DID: {e}")

    msg = _signed_message(ts, nonce, body)
    if not verify_ed25519(msg, sig, pub):
        return FederationVerifyResult(status="invalid", reason="Invalid signature")

    return FederationVerifyResult(status="valid")
