"""Cross-validation: compare Python crypto (cryptography/argon2-cffi) with Zig bridge.

Run BEFORE removing the old Python dependencies to verify byte-for-byte compatibility.
"""

import pytest

# Import Zig bridge functions directly
from src.crypto_bridge import (
    generate_key,
    encrypt,
    decrypt,
    derive_vault_key,
    hash_pin,
    verify_pin,
    generate_ed25519_keypair,
    sign_ed25519,
    verify_ed25519,
    public_key_to_did,
    did_key_to_public_key,
    content_hash,
)


# ── AES-256-GCM Cross-validation ──


def test_zig_encrypt_zig_decrypt():
    """Zig encrypt → Zig decrypt roundtrip."""
    key = generate_key()
    plaintext = b"Hello, TrustMesh!"
    ct = encrypt(plaintext, key)
    pt = decrypt(ct, key)
    assert pt == plaintext


def test_zig_encrypt_python_decrypt():
    """Zig encrypt → Python decrypt."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        pytest.skip("cryptography package not installed")

    key = generate_key()
    plaintext = b"Cross-validation test data"
    ct = encrypt(plaintext, key)

    # Python decrypt: nonce(12) + (ciphertext+tag)
    nonce = ct[:12]
    ciphertext_and_tag = ct[12:]
    aesgcm = AESGCM(key)
    pt = aesgcm.decrypt(nonce, ciphertext_and_tag, None)
    assert pt == plaintext


def test_python_encrypt_zig_decrypt():
    """Python encrypt → Zig decrypt."""
    try:
        import os
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        pytest.skip("cryptography package not installed")

    key = generate_key()
    plaintext = b"Reverse cross-validation"
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext, None)
    # Python format: nonce + ciphertext_with_tag
    data = nonce + ct_with_tag

    pt = decrypt(data, key)
    assert pt == plaintext


# ── Argon2id Cross-validation ──


def test_argon2_vault_key_matches():
    """Same password+salt → identical Argon2id key from Python and Zig."""
    try:
        from argon2.low_level import Type, hash_secret_raw
    except ImportError:
        pytest.skip("argon2-cffi package not installed")

    password = "TrustMesh-demo-2026"
    salt = bytes(range(16))  # Deterministic salt

    # Python derivation
    py_key = hash_secret_raw(
        secret=password.encode(),
        salt=salt,
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
        hash_len=32,
        type=Type.ID,
    )

    # Zig derivation
    zig_key, zig_salt = derive_vault_key(password, salt)

    assert zig_salt == salt, "Salt should be passed through unchanged"
    assert zig_key == py_key, f"Vault keys differ!\nPython: {py_key.hex()}\nZig:    {zig_key.hex()}"


def test_argon2_pin_cross_validation():
    """Zig PIN hash verifiable by both Zig and Python."""
    try:
        from argon2.low_level import Type, hash_secret_raw
    except ImportError:
        pytest.skip("argon2-cffi package not installed")

    pin = "1234"
    zig_hash = hash_pin(pin)

    # Zig verify
    assert verify_pin(pin, zig_hash)

    # Python verify
    salt_hex, hash_hex = zig_hash.split("$")
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    py_hash = hash_secret_raw(
        secret=pin.encode("utf-8"),
        salt=salt,
        time_cost=2,
        memory_cost=19456,
        parallelism=1,
        hash_len=32,
        type=Type.ID,
    )
    assert py_hash == expected, "PIN hash mismatch between Zig and Python"


# ── Ed25519 Cross-validation ──


def test_zig_sign_python_verify():
    """Zig sign → Python verify."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        pytest.skip("cryptography package not installed")

    seed, pub = generate_ed25519_keypair()
    msg = b"Trust is the foundation."
    sig = sign_ed25519(msg, seed)

    # Python verify
    pk = Ed25519PublicKey.from_public_bytes(pub)
    pk.verify(sig, msg)  # Raises InvalidSignature if bad


def test_python_sign_zig_verify():
    """Python sign → Zig verify."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    except ImportError:
        pytest.skip("cryptography package not installed")

    pk = Ed25519PrivateKey.generate()
    msg = b"Cross-validation message"
    sig = pk.sign(msg)
    pub = pk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    # Zig verify
    assert verify_ed25519(msg, sig, pub)


def test_zig_keygen_python_sign_verify():
    """Zig keygen → Python can use the seed to sign and verify."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError:
        pytest.skip("cryptography package not installed")

    seed, pub = generate_ed25519_keypair()
    msg = b"Roundtrip key test"

    # Python sign with Zig-generated seed
    pk = Ed25519PrivateKey.from_private_bytes(seed)
    sig = pk.sign(msg)

    # Zig verify
    assert verify_ed25519(msg, sig, pub)

    # Also check: Python public key matches Zig public key
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    py_pub = pk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    assert py_pub == pub, "Public keys don't match between Zig keygen and Python reconstruction"


# ── SHA-256 Cross-validation ──


def test_sha256_matches():
    """Same content → identical SHA-256 hex from both."""
    import hashlib

    test_strings = ["hello", "", "TrustMesh cross-validation", "🔐"]
    for s in test_strings:
        py_hash = hashlib.sha256(s.encode("utf-8")).hexdigest()
        zig_hash = content_hash(s)
        assert zig_hash == py_hash, f"SHA-256 mismatch for '{s}'"


# ── DID Cross-validation ──


def test_did_roundtrip():
    """Zig DID encode/decode roundtrip."""
    seed, pub = generate_ed25519_keypair()
    did = public_key_to_did(pub)
    assert did.startswith("did:key:z")
    recovered = did_key_to_public_key(did)
    assert recovered == pub
