"""Encryption service — backed by Zig libpodos crypto primitives.

All crypto operations (AES-256-GCM, Argon2id, Ed25519, SHA-256) are
performed in Zig for performance and to eliminate the cryptography/argon2-cffi
Python dependencies.
"""

from src.crypto_bridge import (  # noqa: F401
    KEY_SIZE,
    NONCE_SIZE,
    ARGON2_TIME_COST,
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_SALT_SIZE,
    PIN_ARGON2_TIME_COST,
    PIN_ARGON2_MEMORY_COST,
    PIN_ARGON2_PARALLELISM,
    generate_key,
    derive_vault_key,
    encrypt,
    decrypt,
    encrypt_text,
    decrypt_text,
    content_hash,
    hash_pin,
    verify_pin,
    generate_ed25519_keypair,
    sign_ed25519,
    verify_ed25519,
    public_key_to_did,
    did_key_to_public_key,
    public_key_to_b64,
    b64_to_public_key,
    _base58btc_encode,
    _base58btc_decode,
    _ED25519_MULTICODEC_PREFIX,
    _B58_ALPHABET,
)
