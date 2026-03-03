"""Message bridge — ctypes wrappers for the Zig message store.

Follows credential_bridge.py pattern exactly.
The message body is encrypted/decrypted by the caller using transit_bridge.
This module only manages persistence (create/list/mark-read/delete/sweep/rekey).
"""

import base64
import ctypes
import json
import logging
from typing import Any

log = logging.getLogger(__name__)

_db_handle: Any = None
_initialized: bool = False
_sigs_set: bool = False

c_void_p = ctypes.c_void_p
c_char_p = ctypes.c_char_p
c_int32 = ctypes.c_int32
c_uint32 = ctypes.c_uint32
POINTER = ctypes.POINTER


def _get_lib():
    from src.timeline_bridge import _get_lib as _tl_get_lib
    lib = _tl_get_lib()
    _set_sigs(lib)
    return lib


def _set_sigs(lib):
    """Set argtypes/restype for message C ABI functions (once)."""
    global _sigs_set
    if _sigs_set:
        return
    _sigs_set = True

    # init_tables(db) -> i32
    lib.podos_message_init_tables.argtypes = [c_void_p]
    lib.podos_message_init_tables.restype = c_int32

    # create(...) -> i32  (many args — all strings/blobs with lengths)
    lib.podos_message_create.argtypes = [
        c_void_p,
        c_char_p, c_uint32,   # id
        c_char_p, c_uint32,   # sender_id
        c_char_p, c_uint32,   # sender_username
        c_char_p, c_uint32,   # sender_display_name
        c_char_p, c_uint32,   # sender_pod_url (nullable)
        c_char_p, c_uint32,   # recipient_id
        c_char_p, c_uint32,   # subject
        c_char_p, c_uint32,   # body_encrypted (blob)
        c_char_p, c_uint32,   # body_hash
        c_char_p, c_uint32,   # scope
        c_char_p, c_uint32,   # network_id (nullable)
        c_char_p, c_uint32,   # trust_level
        c_char_p, c_uint32,   # expires_at (nullable)
        c_int32,               # rekey_needed
    ]
    lib.podos_message_create.restype = c_int32

    # list_inbox(db, recipient, r_len, limit, offset, unread_only, out, cap, out_len*) -> i32
    lib.podos_message_list_inbox.argtypes = [
        c_void_p, c_char_p, c_uint32,
        c_int32, c_int32, c_int32,
        c_char_p, c_uint32, POINTER(c_uint32),
    ]
    lib.podos_message_list_inbox.restype = c_int32

    # list_sent(db, sender, s_len, limit, offset, out, cap, out_len*) -> i32
    lib.podos_message_list_sent.argtypes = [
        c_void_p, c_char_p, c_uint32,
        c_int32, c_int32,
        c_char_p, c_uint32, POINTER(c_uint32),
    ]
    lib.podos_message_list_sent.restype = c_int32

    # get_body(db, id, id_len, recipient, r_len, out, cap, out_len*) -> i32
    lib.podos_message_get_body.argtypes = [
        c_void_p, c_char_p, c_uint32,
        c_char_p, c_uint32,
        c_char_p, c_uint32, POINTER(c_uint32),
    ]
    lib.podos_message_get_body.restype = c_int32

    # unread_count(db, recipient, r_len) -> i32
    lib.podos_message_unread_count.argtypes = [c_void_p, c_char_p, c_uint32]
    lib.podos_message_unread_count.restype = c_int32

    # mark_read(db, id, id_len, recipient, r_len) -> i32
    lib.podos_message_mark_read.argtypes = [
        c_void_p, c_char_p, c_uint32, c_char_p, c_uint32,
    ]
    lib.podos_message_mark_read.restype = c_int32

    # soft_delete(db, id, id_len, recipient, r_len) -> i32
    lib.podos_message_soft_delete.argtypes = [
        c_void_p, c_char_p, c_uint32, c_char_p, c_uint32,
    ]
    lib.podos_message_soft_delete.restype = c_int32

    # sweep_expired(db) -> i32
    lib.podos_message_sweep_expired.argtypes = [c_void_p]
    lib.podos_message_sweep_expired.restype = c_int32

    # rekey(db, id, id_len, recipient, r_len, new_body, new_body_len) -> i32
    lib.podos_message_rekey.argtypes = [
        c_void_p, c_char_p, c_uint32,
        c_char_p, c_uint32,
        c_char_p, c_uint32,
    ]
    lib.podos_message_rekey.restype = c_int32

    # list_rekey_pending(db, recipient, r_len, out, cap, out_len*) -> i32
    lib.podos_message_list_rekey_pending.argtypes = [
        c_void_p, c_char_p, c_uint32,
        c_char_p, c_uint32, POINTER(c_uint32),
    ]
    lib.podos_message_list_rekey_pending.restype = c_int32


def _get_db():
    """Return the shared DB handle (opened in embeddings.py)."""
    global _db_handle
    if _db_handle is None:
        import src.embeddings as emb
        _db_handle = emb._db_handle
    return _db_handle


def _ensure_zig():
    """Lazy init: call message init tables (idempotent). For test environments."""
    global _initialized
    if _initialized:
        return
    lib = _get_lib()
    db = _get_db()
    if db is not None:
        lib.podos_message_init_tables(c_void_p(db))
    _initialized = True


# ─── Public API ───────────────────────────────────────────────────────────────

def init_tables() -> None:
    """Create message tables if they don't exist. Call from lifespan."""
    global _initialized
    lib = _get_lib()
    db = _get_db()
    if db is None:
        log.warning("message_bridge: DB handle not ready — skipping table init")
        return
    rc = lib.podos_message_init_tables(c_void_p(db))
    if rc != 0:
        log.error("podos_message_init_tables failed: %d", rc)
    else:
        _initialized = True


def create_message(
    message_id: str,
    sender_id: str,
    sender_username: str,
    sender_display_name: str,
    sender_pod_url: str | None,
    recipient_id: str,
    subject: str,
    body_encrypted: bytes,
    body_hash: str,
    scope: str = "direct",
    network_id: str | None = None,
    trust_level: str = "connected",
    expires_at: str | None = None,
    rekey_needed: bool = False,
) -> str:
    """Persist a new encrypted message. Returns the message_id."""
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        raise RuntimeError("DB not ready")

    mid = message_id.encode()
    sid = sender_id.encode()
    sun = sender_username.encode()
    sdn = sender_display_name.encode()
    spurl = sender_pod_url.encode() if sender_pod_url else None
    rid = recipient_id.encode()
    subj = subject.encode()
    bh = body_hash.encode()
    sc = scope.encode()
    nid = network_id.encode() if network_id else None
    tl = trust_level.encode()
    exp = expires_at.encode() if expires_at else None

    rc = lib.podos_message_create(
        c_void_p(db),
        mid, len(mid),
        sid, len(sid),
        sun, len(sun),
        sdn, len(sdn),
        spurl, len(spurl) if spurl else 0,
        rid, len(rid),
        subj, len(subj),
        body_encrypted, len(body_encrypted),
        bh, len(bh),
        sc, len(sc),
        nid, len(nid) if nid else 0,
        tl, len(tl),
        exp, len(exp) if exp else 0,
        1 if rekey_needed else 0,
    )
    if rc != 0:
        raise RuntimeError(f"podos_message_create failed: {rc}")
    return message_id


def list_inbox(
    recipient_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    unread_only: bool = False,
) -> list[dict]:
    """Return inbox message metadata (no body_encrypted) for the recipient."""
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        return []

    out = ctypes.create_string_buffer(524288)  # 512KB
    out_len = c_uint32(0)
    rid = recipient_id.encode()

    rc = lib.podos_message_list_inbox(
        c_void_p(db), rid, len(rid),
        limit, offset, 1 if unread_only else 0,
        out, 524288, ctypes.byref(out_len),
    )
    if rc != 0:
        log.error("podos_message_list_inbox failed: %d", rc)
        return []
    try:
        return json.loads(out.raw[: out_len.value])
    except json.JSONDecodeError:
        return []


def list_sent(
    sender_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return sent message metadata for the sender."""
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        return []

    out = ctypes.create_string_buffer(524288)
    out_len = c_uint32(0)
    sid = sender_id.encode()

    rc = lib.podos_message_list_sent(
        c_void_p(db), sid, len(sid),
        limit, offset,
        out, 524288, ctypes.byref(out_len),
    )
    if rc != 0:
        log.error("podos_message_list_sent failed: %d", rc)
        return []
    try:
        return json.loads(out.raw[: out_len.value])
    except json.JSONDecodeError:
        return []


def get_body_b64(message_id: str, recipient_id: str) -> str | None:
    """Return base64-encoded encrypted body for decryption by caller. None if not found."""
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        return None

    out = ctypes.create_string_buffer(262144)  # 256KB base64
    out_len = c_uint32(0)
    mid = message_id.encode()
    rid = recipient_id.encode()

    rc = lib.podos_message_get_body(
        c_void_p(db), mid, len(mid), rid, len(rid),
        out, 262144, ctypes.byref(out_len),
    )
    if rc != 0 or out_len.value == 0:
        return None
    return out.raw[: out_len.value].decode("ascii")


def unread_count(recipient_id: str) -> int:
    """Return count of unread messages for recipient."""
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        return 0
    rid = recipient_id.encode()
    result = lib.podos_message_unread_count(c_void_p(db), rid, len(rid))
    return max(0, result)


def mark_read(message_id: str, recipient_id: str) -> bool:
    """Mark message as read. Returns True on success."""
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        return False
    mid = message_id.encode()
    rid = recipient_id.encode()
    rc = lib.podos_message_mark_read(c_void_p(db), mid, len(mid), rid, len(rid))
    return rc == 0


def soft_delete(message_id: str, recipient_id: str) -> bool:
    """Soft-delete message from recipient's inbox. Returns True on success."""
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        return False
    mid = message_id.encode()
    rid = recipient_id.encode()
    rc = lib.podos_message_soft_delete(c_void_p(db), mid, len(mid), rid, len(rid))
    return rc == 0


def sweep_expired() -> int:
    """Delete expired messages. Returns count deleted."""
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        return 0
    result = lib.podos_message_sweep_expired(c_void_p(db))
    return max(0, result)


def rekey_pending(recipient_id: str) -> None:
    """Re-encrypt pod-KEK messages with the user's vault key.

    Called after login when the vault key is loaded into the transit engine.
    Messages stored with rekey_needed=1 (recipient was offline at delivery) are
    re-encrypted from the pod KEK to the user's vault key.
    """
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        return

    from src import transit_bridge

    # Get pending messages
    out = ctypes.create_string_buffer(524288)
    out_len = c_uint32(0)
    rid = recipient_id.encode()

    rc = lib.podos_message_list_rekey_pending(
        c_void_p(db), rid, len(rid),
        out, 524288, ctypes.byref(out_len),
    )
    if rc != 0:
        log.error("podos_message_list_rekey_pending failed: %d", rc)
        return

    try:
        pending = json.loads(out.raw[: out_len.value])
    except json.JSONDecodeError:
        return

    if not pending:
        return

    from src.main import _POD_KEK

    for item in pending:
        msg_id = item.get("id")
        b64 = item.get("body_encrypted_b64")
        if not msg_id or not b64:
            continue
        try:
            old_enc = base64.b64decode(b64)
            # Decrypt with pod KEK
            from src.crypto import decrypt as crypto_decrypt
            plaintext = crypto_decrypt(old_enc, _POD_KEK)
            # Re-encrypt with user's vault key via transit engine
            aad = f"message:{msg_id}"
            new_enc = transit_bridge.encrypt(recipient_id, plaintext, aad=aad)
            # Persist new ciphertext
            mid = msg_id.encode()
            rc2 = lib.podos_message_rekey(
                c_void_p(db),
                mid, len(mid),
                rid, len(rid),
                new_enc, len(new_enc),
            )
            if rc2 != 0:
                log.error("podos_message_rekey failed for %s: %d", msg_id, rc2)
        except Exception as e:
            log.error("rekey_pending: failed to rekey message %s: %s", msg_id, e)
