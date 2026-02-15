"""Encryption service: AES-256-GCM for vault keys and capsule content.

Key derivation uses Argon2id (memory-hard, GPU/ASIC resistant).
Ed25519 keypairs for agent identity and UCAN token signing.
Production: replace password-based derivation with WebAuthn PRF extension.
"""

import base64
import hashlib
import os

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

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


# ── PIN Hashing (Argon2id) ──────────────────────────────────

PIN_ARGON2_TIME_COST = 2
PIN_ARGON2_MEMORY_COST = 19456  # ~19 MiB (fast enough for interactive use)
PIN_ARGON2_PARALLELISM = 1


def hash_pin(pin: str) -> str:
    """Hash a PIN with Argon2id. Returns salt$hash as hex string."""
    salt = os.urandom(16)
    raw_hash = hash_secret_raw(
        secret=pin.encode("utf-8"),
        salt=salt,
        time_cost=PIN_ARGON2_TIME_COST,
        memory_cost=PIN_ARGON2_MEMORY_COST,
        parallelism=PIN_ARGON2_PARALLELISM,
        hash_len=32,
        type=Type.ID,
    )
    return salt.hex() + "$" + raw_hash.hex()


def verify_pin(pin: str, pin_hash: str) -> bool:
    """Verify a PIN against its Argon2id hash."""
    try:
        salt_hex, hash_hex = pin_hash.split("$")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        raw_hash = hash_secret_raw(
            secret=pin.encode("utf-8"),
            salt=salt,
            time_cost=PIN_ARGON2_TIME_COST,
            memory_cost=PIN_ARGON2_MEMORY_COST,
            parallelism=PIN_ARGON2_PARALLELISM,
            hash_len=32,
            type=Type.ID,
        )
        return raw_hash == expected
    except Exception:
        return False


# ── Ed25519 Agent Identity ──────────────────────────────────


# Multicodec prefix for ed25519-pub (0xed) + varint length (0x01 = 1 byte? no, 32 bytes raw)
# Actually: multicodec ed25519-pub = 0xed, 0x01 prefix per did:key spec
_ED25519_MULTICODEC_PREFIX = b"\xed\x01"

# Base58btc alphabet
_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58btc_encode(data: bytes) -> str:
    """Encode bytes to base58btc string."""
    num = int.from_bytes(data, "big")
    result = []
    while num > 0:
        num, rem = divmod(num, 58)
        result.append(_B58_ALPHABET[rem:rem + 1])
    # Preserve leading zero bytes
    for byte in data:
        if byte == 0:
            result.append(b"1")
        else:
            break
    return b"".join(reversed(result)).decode("ascii")


def _base58btc_decode(s: str) -> bytes:
    """Decode a base58btc string back to bytes.

    This is the inverse of _base58btc_encode(). Used for did:key parsing.
    """
    if not s:
        return b""
    num = 0
    for ch in s.encode("ascii"):
        idx = _B58_ALPHABET.find(bytes([ch]))
        if idx == -1:
            raise ValueError("Invalid base58btc character")
        num = num * 58 + idx

    # Convert int to bytes (big endian)
    full = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""

    # Restore leading zero bytes encoded as leading '1's.
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    return (b"\x00" * pad) + full


def generate_ed25519_keypair() -> tuple[bytes, bytes]:
    """Generate an ed25519 keypair.

    Returns (private_key_bytes, public_key_bytes) as raw 32-byte keys.
    """
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private_bytes, public_bytes


def sign_ed25519(message: bytes, private_key_bytes: bytes) -> bytes:
    """Sign a message with an ed25519 private key."""
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    return private_key.sign(message)


def verify_ed25519(message: bytes, signature: bytes, public_key_bytes: bytes) -> bool:
    """Verify an ed25519 signature. Returns True if valid."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as PubKey
    public_key = PubKey.from_public_bytes(public_key_bytes)
    try:
        public_key.verify(signature, message)
        return True
    except InvalidSignature:
        return False


def public_key_to_did(public_key_bytes: bytes) -> str:
    """Convert an ed25519 public key to a did:key identifier.

    Format: did:key:z<base58btc(multicodec_prefix + public_key)>
    """
    multicodec_bytes = _ED25519_MULTICODEC_PREFIX + public_key_bytes
    return f"did:key:z{_base58btc_encode(multicodec_bytes)}"


def public_key_to_b64(public_key_bytes: bytes) -> str:
    """Encode public key bytes to URL-safe base64."""
    return base64.urlsafe_b64encode(public_key_bytes).decode("ascii")


def b64_to_public_key(b64_str: str) -> bytes:
    """Decode URL-safe base64 to public key bytes."""
    return base64.urlsafe_b64decode(b64_str)


def did_key_to_public_key(did: str) -> bytes:
    """Extract raw ed25519 public key bytes from a did:key identifier.

    Supports the did:key:z... form produced by public_key_to_did() (ed25519 only).
    """
    prefix = "did:key:z"
    if not did or not did.startswith(prefix):
        raise ValueError("Unsupported DID format (expected did:key:z...)")

    multicodec = _base58btc_decode(did[len(prefix):])
    if not multicodec.startswith(_ED25519_MULTICODEC_PREFIX):
        raise ValueError("Unsupported did:key multicodec (expected ed25519-pub)")

    pub = multicodec[len(_ED25519_MULTICODEC_PREFIX):]
    if len(pub) != 32:
        raise ValueError("Invalid ed25519 public key length in DID")
    return pub
