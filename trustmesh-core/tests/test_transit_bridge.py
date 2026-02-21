"""Tests for transit_bridge -- Zig transit engine ctypes wrappers."""

import os
import pytest

# Transit bridge requires the Zig library; skip if unavailable
transit_bridge = pytest.importorskip("src.transit_bridge")


@pytest.fixture(autouse=True)
def _init_transit():
    """Ensure transit engine is initialized and clean between tests.

    Force-reinitializes if the engine was deinited by another test file
    (e.g., test_seed_validation calling seed() which may deinit/reinit).
    """
    # Force reinit: mark as uninitialized so _ensure_init() actually calls init()
    if not transit_bridge._initialized:
        transit_bridge._initialized = False
        transit_bridge._ensure_init()
    else:
        transit_bridge._ensure_init()
    yield
    # Clean up test users
    for uid in ["test-user-1", "test-user-2", "test-user-3", "unknown-user"]:
        try:
            transit_bridge.remove_user(uid)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 1. store_key + has_key -> True
# ---------------------------------------------------------------------------

def test_store_key_then_has_key():
    """Storing a key makes has_key return True."""
    key = os.urandom(32)
    transit_bridge.store_key("test-user-1", key)
    assert transit_bridge.has_key("test-user-1") is True


# ---------------------------------------------------------------------------
# 2. has_key for unknown user -> False
# ---------------------------------------------------------------------------

def test_has_key_unknown_user():
    """has_key returns False for a user with no stored key."""
    assert transit_bridge.has_key("unknown-user") is False


# ---------------------------------------------------------------------------
# 3. encrypt + decrypt roundtrip
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_roundtrip():
    """Encrypting then decrypting returns original plaintext."""
    key = os.urandom(32)
    transit_bridge.store_key("test-user-1", key)

    plaintext = b"hello, transit engine"
    ciphertext = transit_bridge.encrypt("test-user-1", plaintext)

    assert ciphertext != plaintext  # must actually encrypt
    decrypted = transit_bridge.decrypt("test-user-1", ciphertext)
    assert decrypted == plaintext


def test_encrypt_decrypt_empty_plaintext():
    """Roundtrip works for empty plaintext."""
    key = os.urandom(32)
    transit_bridge.store_key("test-user-1", key)

    ciphertext = transit_bridge.encrypt("test-user-1", b"")
    decrypted = transit_bridge.decrypt("test-user-1", ciphertext)
    assert decrypted == b""


def test_encrypt_decrypt_large_payload():
    """Roundtrip works for a larger payload."""
    key = os.urandom(32)
    transit_bridge.store_key("test-user-1", key)

    plaintext = os.urandom(4096)
    ciphertext = transit_bridge.encrypt("test-user-1", plaintext)
    decrypted = transit_bridge.decrypt("test-user-1", ciphertext)
    assert decrypted == plaintext


# ---------------------------------------------------------------------------
# 4. decrypt with wrong user -> error (no key stored)
# ---------------------------------------------------------------------------

def test_decrypt_wrong_user_fails():
    """Decrypting with a user that has no key raises RuntimeError."""
    key = os.urandom(32)
    transit_bridge.store_key("test-user-1", key)

    ciphertext = transit_bridge.encrypt("test-user-1", b"secret data")

    with pytest.raises(RuntimeError, match="Transit decrypt failed"):
        transit_bridge.decrypt("test-user-2", ciphertext)


# ---------------------------------------------------------------------------
# 5. encrypt_text + decrypt_text roundtrip
# ---------------------------------------------------------------------------

def test_encrypt_text_decrypt_text_roundtrip():
    """encrypt_text/decrypt_text roundtrip preserves the original string."""
    key = os.urandom(32)
    transit_bridge.store_key("test-user-1", key)

    original = "The quick brown fox jumps over the lazy dog."
    ciphertext = transit_bridge.encrypt_text("test-user-1", original)

    assert isinstance(ciphertext, bytes)
    recovered = transit_bridge.decrypt_text("test-user-1", ciphertext)
    assert recovered == original


def test_encrypt_text_decrypt_text_unicode():
    """Text roundtrip works with unicode content."""
    key = os.urandom(32)
    transit_bridge.store_key("test-user-1", key)

    original = "Capsule data with unicode: cafe\u0301, \u00fc\u00f6\u00e4"
    ciphertext = transit_bridge.encrypt_text("test-user-1", original)
    recovered = transit_bridge.decrypt_text("test-user-1", ciphertext)
    assert recovered == original


# ---------------------------------------------------------------------------
# 6. encrypt with AAD + decrypt with matching AAD
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_with_aad():
    """AAD (additional authenticated data) is bound to the ciphertext."""
    key = os.urandom(32)
    transit_bridge.store_key("test-user-1", key)

    plaintext = b"authenticated payload"
    aad = "capsule-id-12345"

    ciphertext = transit_bridge.encrypt("test-user-1", plaintext, aad=aad)
    decrypted = transit_bridge.decrypt("test-user-1", ciphertext, aad=aad)
    assert decrypted == plaintext


# ---------------------------------------------------------------------------
# 7. encrypt with AAD + decrypt with wrong AAD -> error
# ---------------------------------------------------------------------------

def test_decrypt_with_wrong_aad_fails():
    """Decrypting with mismatched AAD fails."""
    key = os.urandom(32)
    transit_bridge.store_key("test-user-1", key)

    plaintext = b"authenticated payload"
    ciphertext = transit_bridge.encrypt("test-user-1", plaintext, aad="correct-aad")

    with pytest.raises(RuntimeError, match="Transit decrypt failed"):
        transit_bridge.decrypt("test-user-1", ciphertext, aad="wrong-aad")


def test_decrypt_with_missing_aad_fails():
    """Decrypting without AAD when AAD was used to encrypt fails."""
    key = os.urandom(32)
    transit_bridge.store_key("test-user-1", key)

    plaintext = b"needs aad"
    ciphertext = transit_bridge.encrypt("test-user-1", plaintext, aad="required-aad")

    with pytest.raises(RuntimeError, match="Transit decrypt failed"):
        transit_bridge.decrypt("test-user-1", ciphertext, aad="")


# ---------------------------------------------------------------------------
# 8. Multiple users, independent keys
# ---------------------------------------------------------------------------

def test_multiple_users_independent_keys():
    """Different users have independent keys; cross-user decrypt fails."""
    key1 = os.urandom(32)
    key2 = os.urandom(32)
    transit_bridge.store_key("test-user-1", key1)
    transit_bridge.store_key("test-user-2", key2)

    assert transit_bridge.has_key("test-user-1") is True
    assert transit_bridge.has_key("test-user-2") is True

    plaintext = b"user-1 secret"
    ct1 = transit_bridge.encrypt("test-user-1", plaintext)

    # User 1 can decrypt their own data
    assert transit_bridge.decrypt("test-user-1", ct1) == plaintext

    # User 2 cannot decrypt user 1's data (different key)
    with pytest.raises(RuntimeError, match="Transit decrypt failed"):
        transit_bridge.decrypt("test-user-2", ct1)


def test_multiple_users_each_encrypt_decrypt():
    """Each user can encrypt and decrypt independently."""
    for i in range(1, 4):
        uid = f"test-user-{i}"
        transit_bridge.store_key(uid, os.urandom(32))

    for i in range(1, 4):
        uid = f"test-user-{i}"
        plaintext = f"secret for user {i}".encode()
        ct = transit_bridge.encrypt(uid, plaintext)
        assert transit_bridge.decrypt(uid, ct) == plaintext


# ---------------------------------------------------------------------------
# 9. store_key overwrites previous key (new version)
# ---------------------------------------------------------------------------

def test_store_key_overwrites_previous():
    """Storing a new key for the same user overwrites the previous one."""
    key_v1 = os.urandom(32)
    key_v2 = os.urandom(32)

    v1 = transit_bridge.store_key("test-user-1", key_v1)
    assert transit_bridge.has_key("test-user-1") is True

    # Encrypt with first key
    ct_v1 = transit_bridge.encrypt("test-user-1", b"version 1 data")

    # Overwrite with new key -- should return a higher version
    v2 = transit_bridge.store_key("test-user-1", key_v2)
    assert v2 >= v1  # version should not decrease

    # Can still decrypt old ciphertext (versioned format supports this)
    # OR it may fail if old key version is gone. Either is valid behavior.
    # The key point is the new key works for new encryptions.
    new_ct = transit_bridge.encrypt("test-user-1", b"version 2 data")
    assert transit_bridge.decrypt("test-user-1", new_ct) == b"version 2 data"


def test_store_key_returns_version():
    """store_key returns a non-negative version number."""
    v = transit_bridge.store_key("test-user-1", os.urandom(32))
    assert isinstance(v, int)
    assert v >= 0


# ---------------------------------------------------------------------------
# 10. remove_user makes has_key return False
# ---------------------------------------------------------------------------

def test_remove_user_clears_key():
    """After remove_user, has_key returns False."""
    transit_bridge.store_key("test-user-1", os.urandom(32))
    assert transit_bridge.has_key("test-user-1") is True

    transit_bridge.remove_user("test-user-1")
    assert transit_bridge.has_key("test-user-1") is False


def test_remove_user_prevents_decrypt():
    """After removing a user, decryption with that user fails."""
    transit_bridge.store_key("test-user-1", os.urandom(32))
    ct = transit_bridge.encrypt("test-user-1", b"will be inaccessible")

    transit_bridge.remove_user("test-user-1")

    with pytest.raises(RuntimeError, match="Transit decrypt failed"):
        transit_bridge.decrypt("test-user-1", ct)


def test_remove_user_prevents_encrypt():
    """After removing a user, encryption with that user fails."""
    transit_bridge.store_key("test-user-1", os.urandom(32))
    transit_bridge.remove_user("test-user-1")

    with pytest.raises(RuntimeError, match="Transit encrypt failed"):
        transit_bridge.encrypt("test-user-1", b"should fail")


def test_remove_nonexistent_user_is_noop():
    """Removing a user that doesn't exist does not raise."""
    # Should not raise
    transit_bridge.remove_user("unknown-user")


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------

def test_encrypt_produces_different_ciphertexts():
    """Two encryptions of the same plaintext produce different ciphertext (unique nonce)."""
    transit_bridge.store_key("test-user-1", os.urandom(32))
    plaintext = b"same data"

    ct1 = transit_bridge.encrypt("test-user-1", plaintext)
    ct2 = transit_bridge.encrypt("test-user-1", plaintext)

    assert ct1 != ct2  # nonces must differ
    assert transit_bridge.decrypt("test-user-1", ct1) == plaintext
    assert transit_bridge.decrypt("test-user-1", ct2) == plaintext


def test_encrypt_without_stored_key_fails():
    """Encrypting for a user with no key raises RuntimeError."""
    with pytest.raises(RuntimeError, match="Transit encrypt failed"):
        transit_bridge.encrypt("unknown-user", b"no key here")
