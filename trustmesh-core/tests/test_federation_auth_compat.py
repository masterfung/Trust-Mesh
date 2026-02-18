"""Cross-validation: Python federation_auth vs Zig federation_auth FFI.

Tests that signing in one implementation can be verified by the other,
ensuring byte-for-byte compatible message construction and Ed25519 operations.
"""

import ctypes
import json
import time

import pytest

from src.crypto import generate_ed25519_keypair, public_key_to_did
from src.federation_auth import (
    sign_federation_request,
    verify_federation_request,
    reset_federation_auth_state,
    HEADER_TIMESTAMP,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_SIGNATURE_ALG,
)


# ── Helpers ──


def _get_lib():
    """Load the Zig libpodos shared library."""
    from src.timeline_bridge import _get_lib
    return _get_lib()


def _zig_federation_auth_init():
    """Ensure the Zig nonce cache is initialized."""
    lib = _get_lib()
    lib.podos_federation_auth_init()


def _zig_sign(body: bytes, private_key: bytes, method: str = "", path: str = "") -> dict:
    """Call podos_federation_sign via FFI. Returns parsed headers dict."""
    lib = _get_lib()
    method_b = method.encode("utf-8")
    path_b = path.encode("utf-8")
    out_json = ctypes.create_string_buffer(2048)
    out_len = ctypes.c_size_t(0)

    rc = lib.podos_federation_sign(
        body, len(body),
        method_b, len(method_b),
        path_b, len(path_b),
        private_key,
        out_json, 2048,
        ctypes.byref(out_len),
    )
    assert rc == 0, f"podos_federation_sign returned {rc}"
    raw = out_json.raw[: out_len.value].decode("utf-8")
    return json.loads(raw)


def _zig_verify(from_did: str, body: bytes, headers: dict) -> int:
    """Call podos_federation_verify via FFI. Returns 1=valid, 0=missing, -1=invalid."""
    lib = _get_lib()
    did_b = from_did.encode("utf-8")
    headers_json = json.dumps(headers).encode("utf-8")

    rc = lib.podos_federation_verify(
        did_b, len(did_b),
        body, len(body),
        headers_json, len(headers_json),
    )
    return rc


# ── Fixtures ──


@pytest.fixture(autouse=True)
def _reset_nonce_caches():
    """Clear both Python and Zig nonce caches before/after each test."""
    _zig_federation_auth_init()
    lib = _get_lib()
    lib.podos_federation_nonce_reset()
    reset_federation_auth_state()
    yield
    lib.podos_federation_nonce_reset()
    reset_federation_auth_state()


@pytest.fixture
def keypair():
    """Generate a fresh ed25519 keypair and DID."""
    priv, pub = generate_ed25519_keypair()
    did = public_key_to_did(pub)
    return priv, pub, did


# ── Test 1: Python signs -> Python verifies (baseline) ──


def test_python_sign_python_verify(keypair):
    """Baseline: Python signs, Python verifies."""
    priv, _pub, did = keypair
    body = b'{"action": "query", "text": "hello"}'

    headers = sign_federation_request(body, priv, method="POST", path="/api/pod/query")
    result = verify_federation_request(from_did=did, body=body, headers=headers)

    assert result.status == "valid"


# ── Test 2: Zig FFI exports work ──


def test_zig_ffi_sign_and_verify_roundtrip(keypair):
    """Zig signs via FFI, Zig verifies via FFI."""
    priv, _pub, did = keypair
    body = b'{"action": "ping"}'

    headers = _zig_sign(body, priv, method="POST", path="/api/pod/ping")

    # Headers should have the expected keys
    assert HEADER_TIMESTAMP in headers
    assert HEADER_NONCE in headers
    assert HEADER_SIGNATURE in headers
    assert HEADER_SIGNATURE_ALG in headers
    assert headers[HEADER_SIGNATURE_ALG] == "ed25519"

    rc = _zig_verify(did, body, headers)
    assert rc == 1, f"Expected valid (1), got {rc}"


# ── Test 3: Python signs -> Zig verifies ──


def test_python_sign_zig_verify(keypair):
    """Python signs a request, Zig verifies it via FFI."""
    priv, _pub, did = keypair
    body = b'{"query": "medications for patient A"}'

    headers = sign_federation_request(body, priv, method="POST", path="/api/pod/query")
    rc = _zig_verify(did, body, headers)

    assert rc == 1, f"Zig should accept Python signature, got {rc}"


# ── Test 4: Zig signs -> Python verifies ──


def test_zig_sign_python_verify(keypair):
    """Zig signs a request via FFI, Python verifies it."""
    priv, _pub, did = keypair
    body = b'{"query": "trust network members"}'

    headers = _zig_sign(body, priv, method="POST", path="/api/pod/query")
    result = verify_federation_request(from_did=did, body=body, headers=headers)

    assert result.status == "valid", f"Python should accept Zig signature: {result.reason}"


# ── Test 5: Replay detection (reuse same nonce -> rejected) ──


def test_replay_detection_python(keypair):
    """Reusing the same nonce is rejected by Python verifier."""
    priv, _pub, did = keypair
    body = b'{"action": "replay_test"}'
    fixed_nonce = "abcdefghijklmnop"

    headers = sign_federation_request(
        body, priv, method="POST", path="/api/pod/query",
        nonce=fixed_nonce,
    )

    # First verification should succeed
    result1 = verify_federation_request(from_did=did, body=body, headers=headers)
    assert result1.status == "valid"

    # Second verification with same nonce should fail
    result2 = verify_federation_request(from_did=did, body=body, headers=headers)
    assert result2.status == "invalid"
    assert "Replay" in (result2.reason or "")


def test_replay_detection_zig(keypair):
    """Reusing the same nonce is rejected by Zig verifier."""
    priv, _pub, did = keypair
    body = b'{"action": "replay_test_zig"}'

    # Sign with Python (gives us control over the nonce via the headers)
    headers = sign_federation_request(
        body, priv, method="POST", path="/api/pod/query",
        nonce="replaytest12345678",
    )

    # First verify via Zig should succeed
    rc1 = _zig_verify(did, body, headers)
    assert rc1 == 1

    # Second verify via Zig should fail (replay)
    rc2 = _zig_verify(did, body, headers)
    assert rc2 == -1, f"Expected replay rejection (-1), got {rc2}"


# ── Test 6: Expired timestamp rejected ──


def test_expired_timestamp_rejected_python(keypair):
    """Timestamp older than 60s is rejected by Python verifier."""
    priv, _pub, did = keypair
    body = b'{"action": "stale"}'
    old_ts = int(time.time()) - 120  # 2 minutes ago

    headers = sign_federation_request(
        body, priv, method="POST", path="/api/pod/query",
        timestamp=old_ts,
    )
    result = verify_federation_request(from_did=did, body=body, headers=headers)

    assert result.status == "invalid"
    assert "window" in (result.reason or "").lower() or "timestamp" in (result.reason or "").lower()


def test_expired_timestamp_rejected_zig(keypair):
    """Timestamp older than 60s is rejected by Zig verifier."""
    priv, _pub, did = keypair
    body = b'{"action": "stale_zig"}'
    old_ts = int(time.time()) - 120

    headers = sign_federation_request(
        body, priv, method="POST", path="/api/pod/query",
        timestamp=old_ts,
    )
    rc = _zig_verify(did, body, headers)

    assert rc == -1, f"Zig should reject expired timestamp, got {rc}"


# ── Test 7: Tampered body rejected ──


def test_tampered_body_rejected_python(keypair):
    """Modifying the body after signing invalidates the signature (Python verifier)."""
    priv, _pub, did = keypair
    body = b'{"action": "original"}'

    headers = sign_federation_request(body, priv, method="POST", path="/api/pod/query")

    tampered_body = b'{"action": "tampered"}'
    result = verify_federation_request(from_did=did, body=tampered_body, headers=headers)

    assert result.status == "invalid"


def test_tampered_body_rejected_zig(keypair):
    """Modifying the body after signing invalidates the signature (Zig verifier)."""
    priv, _pub, did = keypair
    body = b'{"action": "original"}'

    headers = sign_federation_request(body, priv, method="POST", path="/api/pod/query")

    tampered_body = b'{"action": "tampered"}'
    rc = _zig_verify(did, tampered_body, headers)

    assert rc == -1, f"Zig should reject tampered body, got {rc}"


# ── Test 8: Tampered signature rejected ──


def test_tampered_signature_rejected_python(keypair):
    """Corrupting the signature is rejected by Python verifier."""
    priv, _pub, did = keypair
    body = b'{"action": "sig_test"}'

    headers = sign_federation_request(body, priv, method="POST", path="/api/pod/query")

    # Flip a character in the signature
    sig = headers[HEADER_SIGNATURE]
    # Replace first char with a different one
    replacement = "B" if sig[0] != "B" else "C"
    headers[HEADER_SIGNATURE] = replacement + sig[1:]

    result = verify_federation_request(from_did=did, body=body, headers=headers)
    assert result.status == "invalid"


def test_tampered_signature_rejected_zig(keypair):
    """Corrupting the signature is rejected by Zig verifier."""
    priv, _pub, did = keypair
    body = b'{"action": "sig_test_zig"}'

    headers = sign_federation_request(body, priv, method="POST", path="/api/pod/query")

    sig = headers[HEADER_SIGNATURE]
    replacement = "B" if sig[0] != "B" else "C"
    headers[HEADER_SIGNATURE] = replacement + sig[1:]

    rc = _zig_verify(did, body, headers)
    assert rc == -1, f"Zig should reject tampered signature, got {rc}"


# ── Test 9: Missing headers -> 0 (missing, not invalid) ──


def test_missing_headers_python(keypair):
    """No signature headers = 'missing' status in Python."""
    _priv, _pub, did = keypair
    body = b'{"action": "no_sig"}'

    result = verify_federation_request(from_did=did, body=body, headers={})
    assert result.status == "missing"


def test_missing_headers_zig(keypair):
    """No signature headers = 0 (missing) from Zig FFI."""
    _priv, _pub, did = keypair
    body = b'{"action": "no_sig_zig"}'

    rc = _zig_verify(did, body, {})
    assert rc == 0, f"Zig should return 0 for missing headers, got {rc}"


# ── Test 10: Empty body signing/verification ──


def test_empty_body_python_sign_python_verify(keypair):
    """Empty body can be signed and verified by Python."""
    priv, _pub, did = keypair
    body = b""

    headers = sign_federation_request(body, priv, method="GET", path="/api/pod/info")
    result = verify_federation_request(from_did=did, body=body, headers=headers)

    assert result.status == "valid"


def test_empty_body_cross_compat(keypair):
    """Empty body: Python signs, Zig verifies and vice versa."""
    priv, _pub, did = keypair
    body = b""

    # Python sign -> Zig verify
    headers = sign_federation_request(body, priv, method="GET", path="/api/pod/info")
    rc = _zig_verify(did, body, headers)
    assert rc == 1, f"Zig should accept empty body signed by Python, got {rc}"

    # Reset nonces for the reverse test
    _get_lib().podos_federation_nonce_reset()
    reset_federation_auth_state()

    # Zig sign -> Python verify
    headers2 = _zig_sign(body, priv, method="GET", path="/api/pod/info")
    result = verify_federation_request(from_did=did, body=body, headers=headers2)
    assert result.status == "valid", f"Python should accept empty body signed by Zig: {result.reason}"


# ── Test 11: Large body (10KB) signing/verification ──


def test_large_body_python_sign_zig_verify(keypair):
    """Large body (10KB): Python signs, Zig verifies."""
    priv, _pub, did = keypair
    body = b"A" * 10240  # 10KB

    headers = sign_federation_request(body, priv, method="POST", path="/api/pod/query")
    rc = _zig_verify(did, body, headers)

    assert rc == 1, f"Zig should verify 10KB body signed by Python, got {rc}"


def test_large_body_zig_sign_python_verify(keypair):
    """Large body (10KB): Zig signs, Python verifies."""
    priv, _pub, did = keypair
    body = b"B" * 10240  # 10KB

    headers = _zig_sign(body, priv, method="POST", path="/api/pod/query")
    result = verify_federation_request(from_did=did, body=body, headers=headers)

    assert result.status == "valid", f"Python should verify 10KB body signed by Zig: {result.reason}"


# ── Test 12: Nonce reset clears cache ──


def test_nonce_reset_clears_zig_cache(keypair):
    """podos_federation_nonce_reset() clears the Zig nonce cache, allowing replay."""
    priv, _pub, did = keypair
    body = b'{"action": "reset_test"}'

    headers = sign_federation_request(
        body, priv, method="POST", path="/api/pod/query",
        nonce="resetcachetest1234",
    )

    # First verify succeeds
    rc1 = _zig_verify(did, body, headers)
    assert rc1 == 1

    # Without reset, replay is blocked
    rc2 = _zig_verify(did, body, headers)
    assert rc2 == -1

    # Reset the nonce cache
    _get_lib().podos_federation_nonce_reset()

    # After reset, same nonce is accepted again
    rc3 = _zig_verify(did, body, headers)
    assert rc3 == 1, f"After nonce reset, should accept again, got {rc3}"


def test_nonce_reset_clears_python_cache(keypair):
    """reset_federation_auth_state() clears the Python nonce cache."""
    priv, _pub, did = keypair
    body = b'{"action": "py_reset_test"}'
    fixed_nonce = "pyreset_nonce_test"

    headers = sign_federation_request(
        body, priv, method="POST", path="/api/pod/query",
        nonce=fixed_nonce,
    )

    result1 = verify_federation_request(from_did=did, body=body, headers=headers)
    assert result1.status == "valid"

    # Replay blocked
    result2 = verify_federation_request(from_did=did, body=body, headers=headers)
    assert result2.status == "invalid"

    # Reset
    reset_federation_auth_state()

    # After reset, accepted again
    result3 = verify_federation_request(from_did=did, body=body, headers=headers)
    assert result3.status == "valid"


# ── Legacy format (no method/path) cross-compat ──


def test_legacy_format_python_sign_zig_verify(keypair):
    """Legacy format (no method/path): Python signs, Zig verifies."""
    priv, _pub, did = keypair
    body = b'{"legacy": true}'

    # No method/path = legacy format
    headers = sign_federation_request(body, priv)
    rc = _zig_verify(did, body, headers)

    assert rc == 1, f"Zig should accept legacy-format Python signature, got {rc}"


def test_legacy_format_zig_sign_python_verify(keypair):
    """Legacy format (no method/path): Zig signs, Python verifies."""
    priv, _pub, did = keypair
    body = b'{"legacy": true}'

    # Empty method/path = legacy format
    headers = _zig_sign(body, priv, method="", path="")
    result = verify_federation_request(from_did=did, body=body, headers=headers)

    assert result.status == "valid", f"Python should accept legacy-format Zig signature: {result.reason}"
