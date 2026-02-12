"""Encryption service: AES-256-GCM for vault keys and capsule content."""

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_SIZE = 32  # AES-256
NONCE_SIZE = 12  # GCM standard


def generate_key() -> bytes:
    """Generate a random AES-256 key."""
    return AESGCM.generate_key(bit_length=256)


def derive_vault_key(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Derive a vault key from password using PBKDF2.

    Returns (derived_key, salt).
    For hackathon: simplified password-based derivation.
    Production: replace with WebAuthn PRF extension.
    """
    if salt is None:
        salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations=100_000, dklen=KEY_SIZE)
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
