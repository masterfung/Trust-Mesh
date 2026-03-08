"""Encryption service — backed by Zig libpodos crypto primitives.

All crypto operations (AES-256-GCM, Argon2id, Ed25519, SHA-256) are
performed in Zig for performance and to eliminate the cryptography/argon2-cffi
Python dependencies.
"""

import base64

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


def generate_x25519_keypair() -> tuple[str, str]:
    """Generate X25519 keypair for ECDH relay payload encryption.

    Returns (private_key_b64url, public_key_b64url) — both raw 32-byte keys
    encoded as base64url without padding.
    """
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

    priv = X25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    priv_b64 = base64.urlsafe_b64encode(priv_bytes).rstrip(b"=").decode()
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()
    return priv_b64, pub_b64
