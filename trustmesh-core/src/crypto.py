"""Encryption service: AES-256-GCM for vault keys and capsule content.

Key derivation uses Argon2id (memory-hard, GPU/ASIC resistant).
Production: replace password-based derivation with WebAuthn PRF extension.
"""

import hashlib
import os

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_SIZE = 32  # AES-256
NONCE_SIZE = 12  # GCM standard

# Argon2id parameters (OWASP recommended for password hashing)
ARGON2_TIME_COST = 3  # iterations
ARGON2_MEMORY_COST = 65536  # 64 MiB
ARGON2_PARALLELISM = 4
ARGON2_SALT_SIZE = 16


def generate_key() -> bytes:
    """Generate a random AES-256 key."""
    return AESGCM.generate_key(bit_length=256)


def derive_vault_key(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Derive a vault key from password using Argon2id.

    Returns (derived_key, salt).
    Argon2id is memory-hard, resistant to GPU/ASIC brute-force attacks.
    Production: replace with WebAuthn PRF extension.
    """
    if salt is None:
        salt = os.urandom(ARGON2_SALT_SIZE)
    key = hash_secret_raw(
        secret=password.encode(),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=KEY_SIZE,
        type=Type.ID,  # Argon2id — hybrid of Argon2i + Argon2d
    )
    return key, salt


def encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt data with AES-256-GCM. Returns nonce || ciphertext."""
    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt(data: bytes, key: bytes) -> bytes:
    """Decrypt AES-256-GCM data. Expects nonce || ciphertext."""
    nonce = data[:NONCE_SIZE]
    ciphertext = data[NONCE_SIZE:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def encrypt_text(plaintext: str, key: bytes) -> bytes:
    """Encrypt a string with AES-256-GCM."""
    return encrypt(plaintext.encode("utf-8"), key)


def decrypt_text(data: bytes, key: bytes) -> str:
    """Decrypt AES-256-GCM data back to string."""
    return decrypt(data, key).decode("utf-8")


def content_hash(content: str) -> str:
    """SHA-256 hash of content for change detection."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
