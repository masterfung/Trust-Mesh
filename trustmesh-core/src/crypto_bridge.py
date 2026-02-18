"""Crypto bridge — ctypes wrappers calling Zig libpodos crypto primitives.

Drop-in replacement for crypto.py functions. Same signatures, backed by Zig.
"""

import base64
import ctypes
from ctypes import c_uint32

KEY_SIZE = 32
NONCE_SIZE = 12

# Argon2id parameters (kept for reference, actual values are in Zig)
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 65536
ARGON2_PARALLELISM = 4
ARGON2_SALT_SIZE = 16

PIN_ARGON2_TIME_COST = 2
PIN_ARGON2_MEMORY_COST = 19456
PIN_ARGON2_PARALLELISM = 1


def _get_lib():
    """Get the loaded libpodos library."""
    from src.timeline_bridge import _get_lib as _tl_get_lib
    return _tl_get_lib()


def generate_key() -> bytes:
    """Generate a random AES-256 key."""
    lib = _get_lib()
    out = ctypes.create_string_buffer(32)
    lib.podos_crypto_generate_key(out)
    return out.raw


def derive_vault_key(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Derive a vault key from password using Argon2id. Returns (key, salt)."""
    lib = _get_lib()
    pw = password.encode("utf-8")
    out_key = ctypes.create_string_buffer(32)
    out_salt = ctypes.create_string_buffer(16)

    if salt is not None:
        rc = lib.podos_crypto_derive_vault_key(pw, len(pw), salt, len(salt), out_key, out_salt)
    else:
        rc = lib.podos_crypto_derive_vault_key(pw, len(pw), None, 0, out_key, out_salt)

    if rc != 0:
        raise RuntimeError("Argon2id key derivation failed")
    return out_key.raw, out_salt.raw


def encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt data with AES-256-GCM. Returns nonce || ciphertext || tag."""
    lib = _get_lib()
    capacity = NONCE_SIZE + len(plaintext) + 16 + 16  # Extra margin
    out = ctypes.create_string_buffer(capacity)
    out_len = c_uint32(0)
    rc = lib.podos_crypto_encrypt(plaintext, len(plaintext), key, out, capacity, ctypes.byref(out_len))
    if rc != 0:
        raise RuntimeError("AES-256-GCM encryption failed")
    return out.raw[:out_len.value]


def decrypt(data: bytes, key: bytes) -> bytes:
    """Decrypt AES-256-GCM data. Expects nonce || ciphertext || tag."""
    lib = _get_lib()
    capacity = len(data)  # Plaintext is always smaller
    out = ctypes.create_string_buffer(capacity)
    out_len = c_uint32(0)
    rc = lib.podos_crypto_decrypt(data, len(data), key, out, capacity, ctypes.byref(out_len))
    if rc != 0:
        raise RuntimeError("AES-256-GCM decryption failed")
    return out.raw[:out_len.value]


def encrypt_text(plaintext: str, key: bytes) -> bytes:
    """Encrypt a string with AES-256-GCM."""
    return encrypt(plaintext.encode("utf-8"), key)


def decrypt_text(data: bytes, key: bytes) -> str:
    """Decrypt AES-256-GCM data back to string."""
    return decrypt(data, key).decode("utf-8")


def content_hash(content: str) -> str:
    """SHA-256 hash of content for change detection."""
    lib = _get_lib()
    data = content.encode("utf-8")
    out = ctypes.create_string_buffer(64)
    lib.podos_crypto_sha256_hex(data, len(data), out)
    return out.raw[:64].decode("ascii")


# ── PIN Hashing ──


def hash_pin(pin: str) -> str:
    """Hash a PIN with Argon2id. Returns salt$hash as hex string."""
    lib = _get_lib()
    pin_b = pin.encode("utf-8")
    out = ctypes.create_string_buffer(128)
    out_len = c_uint32(0)
    rc = lib.podos_crypto_hash_pin(pin_b, len(pin_b), out, ctypes.byref(out_len))
    if rc != 0:
        raise RuntimeError("PIN hashing failed")
    return out.raw[:out_len.value].decode("ascii")


def verify_pin(pin: str, pin_hash: str) -> bool:
    """Verify a PIN against its Argon2id hash."""
    lib = _get_lib()
    pin_b = pin.encode("utf-8")
    hash_b = pin_hash.encode("ascii")
    return lib.podos_crypto_verify_pin(pin_b, len(pin_b), hash_b, len(hash_b)) == 1


# ── Ed25519 ──


_ED25519_MULTICODEC_PREFIX = b"\xed\x01"
_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def generate_ed25519_keypair() -> tuple[bytes, bytes]:
    """Generate an ed25519 keypair. Returns (private_key_bytes, public_key_bytes)."""
    lib = _get_lib()
    out_seed = ctypes.create_string_buffer(32)
    out_pub = ctypes.create_string_buffer(32)
    lib.podos_crypto_ed25519_keygen(out_seed, out_pub)
    return out_seed.raw, out_pub.raw


def sign_ed25519(message: bytes, private_key_bytes: bytes) -> bytes:
    """Sign a message with an ed25519 private key (32-byte seed)."""
    lib = _get_lib()
    out_sig = ctypes.create_string_buffer(64)
    rc = lib.podos_crypto_ed25519_sign(message, len(message), private_key_bytes, out_sig)
    if rc != 0:
        raise RuntimeError("Ed25519 signing failed")
    return out_sig.raw


def verify_ed25519(message: bytes, signature: bytes, public_key_bytes: bytes) -> bool:
    """Verify an ed25519 signature. Returns True if valid."""
    lib = _get_lib()
    return lib.podos_crypto_ed25519_verify(
        message, len(message), signature, public_key_bytes
    ) == 1


def public_key_to_did(public_key_bytes: bytes) -> str:
    """Convert ed25519 public key to did:key identifier."""
    lib = _get_lib()
    out = ctypes.create_string_buffer(128)
    length = lib.podos_crypto_pubkey_to_did(public_key_bytes, out, 128)
    if length <= 0:
        raise RuntimeError("Failed to convert public key to DID")
    return out.raw[:length].decode("ascii")


def did_key_to_public_key(did: str) -> bytes:
    """Extract raw ed25519 public key bytes from did:key identifier."""
    lib = _get_lib()
    did_b = did.encode("ascii")
    out = ctypes.create_string_buffer(32)
    rc = lib.podos_crypto_did_to_pubkey(did_b, len(did_b), out)
    if rc != 0:
        raise ValueError("Unsupported DID format (expected did:key:z...)")
    return out.raw


# ── Base64 helpers (pure Python — no Zig needed) ──


def public_key_to_b64(public_key_bytes: bytes) -> str:
    """Encode public key bytes to URL-safe base64."""
    return base64.urlsafe_b64encode(public_key_bytes).decode("ascii")


def b64_to_public_key(b64_str: str) -> bytes:
    """Decode URL-safe base64 to public key bytes."""
    return base64.urlsafe_b64decode(b64_str)


# ── Base58btc (kept for backward compat, uses Zig internally via DID ops) ──
# These are only used by the DID functions which are now in Zig.
# Keep Python implementations for any direct callers.

def _base58btc_encode(data: bytes) -> str:
    """Encode bytes to base58btc string."""
    num = int.from_bytes(data, "big")
    result = []
    while num > 0:
        num, rem = divmod(num, 58)
        result.append(_B58_ALPHABET[rem:rem + 1])
    for byte in data:
        if byte == 0:
            result.append(b"1")
        else:
            break
    return b"".join(reversed(result)).decode("ascii")


def _base58btc_decode(s: str) -> bytes:
    """Decode a base58btc string back to bytes."""
    if not s:
        return b""
    num = 0
    for ch in s.encode("ascii"):
        idx = _B58_ALPHABET.find(bytes([ch]))
        if idx == -1:
            raise ValueError("Invalid base58btc character")
        num = num * 58 + idx
    full = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    return (b"\x00" * pad) + full
