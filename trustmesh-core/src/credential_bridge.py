"""Credential bridge — thin ctypes wrappers for agent tools only.

Routes (POST/GET/DELETE /api/credentials) are handled natively by
handlers/credentials.zig. This file is ONLY for agent tool dispatch
(list_credentials, manage_credential) that remain in the Python MCP layer.
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
    """Set argtypes/restype for credential C ABI functions (once)."""
    global _sigs_set
    if _sigs_set:
        return
    _sigs_set = True

    # init_tables(db) -> i32
    lib.podos_credential_init_tables.argtypes = [c_void_p]
    lib.podos_credential_init_tables.restype = c_int32

    # create(db, id, id_len, owner, owner_len, name, name_len, svc, svc_len,
    #        cat, cat_len, secret_enc, sec_len, tools_json, tools_len, exp, exp_len) -> i32
    lib.podos_credential_create.argtypes = [
        c_void_p,
        c_char_p, c_uint32, c_char_p, c_uint32,
        c_char_p, c_uint32, c_char_p, c_uint32,
        c_char_p, c_uint32, c_char_p, c_uint32,
        c_char_p, c_uint32, c_char_p, c_uint32,
    ]
    lib.podos_credential_create.restype = c_int32

    # list(db, owner, owner_len, out, out_cap, out_len*) -> i32
    lib.podos_credential_list.argtypes = [
        c_void_p, c_char_p, c_uint32,
        c_char_p, c_uint32, POINTER(c_uint32),
    ]
    lib.podos_credential_list.restype = c_int32

    # for_tool(db, owner, owner_len, tool, tool_len, out, out_cap, out_len*) -> i32
    lib.podos_credential_for_tool.argtypes = [
        c_void_p, c_char_p, c_uint32,
        c_char_p, c_uint32,
        c_char_p, c_uint32, POINTER(c_uint32),
    ]
    lib.podos_credential_for_tool.restype = c_int32

    # update_use(db, id, id_len, actor, actor_len) -> i32
    lib.podos_credential_update_use.argtypes = [
        c_void_p, c_char_p, c_uint32, c_char_p, c_uint32,
    ]
    lib.podos_credential_update_use.restype = c_int32

    # deactivate(db, id, id_len, owner, owner_len) -> i32
    lib.podos_credential_deactivate.argtypes = [
        c_void_p, c_char_p, c_uint32, c_char_p, c_uint32,
    ]
    lib.podos_credential_deactivate.restype = c_int32

    # audit_append(db, cred_id, cid_len, op, op_len, actor, actor_len,
    #              tool, tool_len, share, share_len, ip, ip_len,
    #              decision, dec_len, details, det_len) -> i32
    lib.podos_credential_audit_append.argtypes = [
        c_void_p,
        c_char_p, c_uint32, c_char_p, c_uint32,
        c_char_p, c_uint32, c_char_p, c_uint32,
        c_char_p, c_uint32, c_char_p, c_uint32,
        c_char_p, c_uint32, c_char_p, c_uint32,
    ]
    lib.podos_credential_audit_append.restype = c_int32

    # sweep_expiry(db) -> i32
    lib.podos_credential_sweep_expiry.argtypes = [c_void_p]
    lib.podos_credential_sweep_expiry.restype = c_int32


def _get_db():
    """Return the shared DB handle (opened in embeddings.py)."""
    global _db_handle
    if _db_handle is None:
        import src.embeddings as emb
        _db_handle = emb._db_handle
    return _db_handle


def _ensure_zig():
    """Lazy init: call credential init tables (idempotent). For test environments."""
    global _initialized
    if _initialized:
        return
    lib = _get_lib()
    db = _get_db()
    if db is not None:
        lib.podos_credential_init_tables(c_void_p(db))
    _initialized = True


# ─── Public API ───────────────────────────────────────────────────────────────

def init_tables() -> None:
    """Create credential tables if they don't exist. Call from lifespan."""
    global _initialized
    lib = _get_lib()
    db = _get_db()
    if db is None:
        log.warning("credential_bridge: DB handle not ready — skipping table init")
        return
    rc = lib.podos_credential_init_tables(c_void_p(db))
    if rc != 0:
        log.error("podos_credential_init_tables failed: %d", rc)
    else:
        _initialized = True


def create_credential(
    owner_id: str,
    name: str,
    service: str,
    secret: str,
    scoped_tools: list[str],
    category: str = "",
    expires_at: str | None = None,
) -> str:
    """Encrypt + store a credential. Returns the new credential ID.

    The plaintext `secret` is encrypted by the Zig transit engine immediately.
    It is never stored, logged, or returned.
    """
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        raise RuntimeError("DB not ready")

    from src.transit_bridge import encrypt

    # Encrypt via transit engine
    try:
        enc_bytes = encrypt(owner_id, secret.encode(), aad="credential:secret")
    except Exception as e:
        raise RuntimeError(f"Encryption failed (is vault unlocked?): {e}") from e

    # Generate ID from Zig helper (just use os.urandom + hex)
    import uuid
    new_id = str(uuid.uuid4()).replace("-", "")[:32]

    tools_json = json.dumps(scoped_tools).encode()
    uid = owner_id.encode()
    cid = new_id.encode()
    nm = name.encode()
    svc = service.encode()
    cat = category.encode()
    exp = expires_at.encode() if expires_at else None

    # podos_credential_create(db, id, id_len, owner_id, owner_len,
    #   name, name_len, service, service_len, category, cat_len,
    #   secret_enc, secret_enc_len, scoped_tools_json, tools_len,
    #   expires_at, exp_len)
    rc = lib.podos_credential_create(
        c_void_p(db),
        cid, len(cid),
        uid, len(uid),
        nm, len(nm),
        svc, len(svc),
        cat, len(cat),
        enc_bytes, len(enc_bytes),
        tools_json, len(tools_json),
        exp, len(exp) if exp else 0,
    )
    if rc != 0:
        raise RuntimeError(f"podos_credential_create failed: {rc}")

    # Audit: created
    _audit_append(db, lib, new_id, "created", owner_id)

    return new_id


def list_credentials(owner_id: str) -> list[dict]:
    """Return credential metadata (no secrets) for the owner."""
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        return []

    out = ctypes.create_string_buffer(65536)
    out_len = ctypes.c_uint32(0)
    uid = owner_id.encode()

    rc = lib.podos_credential_list(c_void_p(db), uid, len(uid), out, 65536, ctypes.byref(out_len))
    if rc != 0:
        log.error("podos_credential_list failed: %d", rc)
        return []

    try:
        return json.loads(out.raw[: out_len.value])
    except json.JSONDecodeError:
        return []


def get_credential_for_tool(owner_id: str, tool_name: str) -> list[dict]:
    """Return credentials scoped to `tool_name` (includes encrypted blob for agent use).

    Each item has: {id, name, service, scoped_tools, secret_encrypted_b64}.
    The agent should decrypt via transit_bridge when needed.
    """
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        return []

    out = ctypes.create_string_buffer(65536)
    out_len = ctypes.c_uint32(0)
    uid = owner_id.encode()
    tn = tool_name.encode()

    rc = lib.podos_credential_for_tool(
        c_void_p(db), uid, len(uid), tn, len(tn), out, 65536, ctypes.byref(out_len)
    )
    if rc != 0:
        log.error("podos_credential_for_tool failed: %d", rc)
        return []

    try:
        items = json.loads(out.raw[: out_len.value])
    except json.JSONDecodeError:
        return []

    # Decrypt each secret inline for agent use
    from src.transit_bridge import decrypt

    result = []
    for item in items:
        b64 = item.pop("secret_encrypted_b64", None)
        if b64:
            try:
                enc_bytes = base64.b64decode(b64)
                secret = decrypt(owner_id, enc_bytes, aad="credential:secret")
                item["secret"] = secret.decode()
            except Exception as e:
                log.error("Failed to decrypt credential %s: %s", item.get("id"), e)
                item["secret"] = None
        result.append(item)

    return result


def record_use(cred_id: str, actor_id: str, tool_name: str) -> None:
    """Record a credential use in the audit trail."""
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        return

    # Update use_count
    cid = cred_id.encode()
    uid = actor_id.encode()
    lib.podos_credential_update_use(c_void_p(db), cid, len(cid), uid, len(uid))

    # Audit
    _audit_append(db, lib, cred_id, "used", actor_id, tool_name=tool_name)


def deactivate_credential(cred_id: str, owner_id: str) -> None:
    """Soft-delete a credential."""
    _ensure_zig()
    lib = _get_lib()
    db = _get_db()
    if db is None:
        raise RuntimeError("DB not ready")

    _audit_append(db, lib, cred_id, "deactivated", owner_id)

    cid = cred_id.encode()
    uid = owner_id.encode()
    rc = lib.podos_credential_deactivate(c_void_p(db), cid, len(cid), uid, len(uid))
    if rc == -3:
        raise PermissionError("Access denied")
    if rc != 0:
        raise RuntimeError(f"Deactivation failed: {rc}")


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _audit_append(db, lib, cred_id: str, operation: str, actor_id: str, tool_name: str | None = None) -> None:
    """Fire-and-forget audit append (errors are logged, not raised for non-critical ops)."""
    cid = cred_id.encode()
    op = operation.encode()
    uid = actor_id.encode()
    tn = tool_name.encode() if tool_name else None
    decision = b"allowed"

    rc = lib.podos_credential_audit_append(
        c_void_p(db),
        cid, len(cid),
        op, len(op),
        uid, len(uid),
        tn, len(tn) if tn else 0,
        None, 0,  # share_id
        None, 0,  # ip_fp
        decision, len(decision),
        None, 0,  # details_json
    )
    if rc != 0:
        log.error("podos_credential_audit_append failed: %d (op=%s, cred=%s)", rc, operation, cred_id)
