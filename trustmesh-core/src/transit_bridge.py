"""Transit bridge — ctypes wrappers calling Zig transit engine.

Keys are stored in Zig memory and never returned to Python after initial store.
All encrypt/decrypt operations happen inside Zig with the key handle.
"""

import ctypes
from ctypes import c_int32, c_uint32

_initialized = False


def _get_lib():
    from src.timeline_bridge import _get_lib as _tl_get_lib
    return _tl_get_lib()


def init() -> None:
    """Initialize the transit engine. Call once on startup."""
    global _initialized
    if _initialized:
        return
    lib = _get_lib()
    rc = lib.podos_transit_init()
    if rc != 0:
        raise RuntimeError("Failed to initialize transit engine")
    _initialized = True


def _ensure_init():
    """Lazy init for test environments where lifespan doesn't run."""
    global _initialized
    if not _initialized:
        try:
            init()
        except Exception:
            pass


def deinit() -> None:
    """Destroy the transit engine. secureZero all keys."""
    global _initialized
    if not _initialized:
        return
    lib = _get_lib()
    lib.podos_transit_deinit()
    _initialized = False


def store_key(user_id: str, key: bytes) -> int:
    """Store a vault key for a user. Returns version number.

    After this call, the key material should be zeroed in Python.
    """
    _ensure_init()
    lib = _get_lib()
    uid = user_id.encode("utf-8")
    rc = lib.podos_transit_store_key(uid, len(uid), key)
    if rc < 0:
        raise RuntimeError(f"Failed to store key for {user_id}: {rc}")
    return rc


def encrypt(user_id: str, plaintext: bytes, aad: str = "") -> bytes:
    """Encrypt plaintext for a user. AAD is bound to the ciphertext.

    Output format: "v{N}.{nonce}{ciphertext}{tag}"
    """
    _ensure_init()
    lib = _get_lib()
    uid = user_id.encode("utf-8")
    aad_b = aad.encode("utf-8")
    # Output buffer: version prefix (max 8) + nonce(12) + data + tag(16) + margin
    capacity = 8 + 12 + len(plaintext) + 16 + 16
    out = ctypes.create_string_buffer(capacity)
    out_len = c_uint32(0)
    rc = lib.podos_transit_encrypt(
        uid, len(uid),
        plaintext, len(plaintext),
        aad_b, len(aad_b),
        out, capacity,
        ctypes.byref(out_len),
    )
    if rc != 0:
        raise RuntimeError(f"Transit encrypt failed for {user_id}: {rc}")
    return out.raw[:out_len.value]


def encrypt_text(user_id: str, plaintext: str, aad: str = "") -> bytes:
    """Encrypt a string for a user."""
    return encrypt(user_id, plaintext.encode("utf-8"), aad)


def decrypt(user_id: str, ciphertext: bytes, aad: str = "") -> bytes:
    """Decrypt ciphertext for a user. Handles versioned and legacy formats."""
    _ensure_init()
    lib = _get_lib()
    uid = user_id.encode("utf-8")
    aad_b = aad.encode("utf-8")
    capacity = len(ciphertext) + 16  # plaintext is always smaller
    out = ctypes.create_string_buffer(capacity)
    out_len = c_uint32(0)
    rc = lib.podos_transit_decrypt(
        uid, len(uid),
        ciphertext, len(ciphertext),
        aad_b, len(aad_b),
        out, capacity,
        ctypes.byref(out_len),
    )
    if rc != 0:
        raise RuntimeError(f"Transit decrypt failed for {user_id}: {rc}")
    return out.raw[:out_len.value]


def decrypt_text(user_id: str, ciphertext: bytes, aad: str = "") -> str:
    """Decrypt ciphertext for a user back to string."""
    return decrypt(user_id, ciphertext, aad).decode("utf-8")


def rotate_key(user_id: str) -> int:
    """Rotate key for a user. Returns new version number."""
    _ensure_init()
    lib = _get_lib()
    uid = user_id.encode("utf-8")
    rc = lib.podos_transit_rotate(uid, len(uid))
    if rc < 0:
        raise RuntimeError(f"Failed to rotate key for {user_id}: {rc}")
    return rc


def remove_user(user_id: str) -> None:
    """Remove all keys for a user. secureZero all material."""
    _ensure_init()
    lib = _get_lib()
    uid = user_id.encode("utf-8")
    lib.podos_transit_remove(uid, len(uid))


def has_key(user_id: str) -> bool:
    """Check if a user has a key loaded."""
    _ensure_init()
    lib = _get_lib()
    uid = user_id.encode("utf-8")
    return lib.podos_transit_has_key(uid, len(uid)) == 1


def _zero_bytes(data: bytes) -> None:
    """Best-effort zero of a Python bytes/bytearray object.

    CPython bytes are immutable, so we use ctypes to write zeros into the buffer.
    This is not guaranteed to work on all Python implementations.
    """
    if isinstance(data, (bytes, bytearray)) and len(data) > 0:
        try:
            ctypes.memset(ctypes.c_char_p(data), 0, len(data))
        except Exception:
            pass
