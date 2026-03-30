"""Propagation bridge — ctypes wrappers for Zig propagation module.

Provides Python-callable functions for:
- infer_propagation(): category→propagation mapping (comptime keywords in Zig)
- propagation_targets(): SQL join for notification fan-out targets
- create_notifications(): batch INSERT into notifications table

Falls back to pure-Python implementations when Zig library is unavailable.
"""

import logging

log = logging.getLogger(__name__)

_lib = None
_initialized = False


def _get_lib():
    global _lib, _initialized
    if _initialized:
        return _lib
    _initialized = True
    try:
        from src.transit_bridge import _get_lib as _get_transit_lib
        _lib = _get_transit_lib()
        if _lib and hasattr(_lib, "podos_infer_propagation_export"):
            log.info("propagation_bridge: Zig propagation module available")
        else:
            _lib = None
            log.info("propagation_bridge: Zig propagation export not found, using Python fallback")
    except Exception as e:
        log.info("propagation_bridge: Zig not available (%s), using Python fallback", e)
        _lib = None
    return _lib


# ── Propagation inference ──

# Python fallback categories (mirrors propagation.zig comptime lists)
_BROADCAST_CATEGORIES = frozenset({"health", "medical"})
_NOTIFY_CATEGORIES = frozenset({"family"})
_FORCED_SILENT_CATEGORIES = frozenset({"financial", "personal"})


def infer_propagation(
    explicit: str | None,
    category: str,
    visibility: str,
) -> str:
    """Determine propagation level for a capsule.

    Rules:
    1. Private visibility → always silent
    2. Financial/personal category → always silent
    3. Explicit value → use it (if valid)
    4. Health → broadcast, family → notify
    5. Default → silent
    """
    # Rule 1: private always silent
    if visibility == "private":
        return "silent"

    # Rule 2: forced silent categories
    if category in _FORCED_SILENT_CATEGORIES:
        return "silent"

    # Rule 3: explicit override
    if explicit and explicit in ("silent", "notify", "broadcast"):
        return explicit

    # Rule 4: category defaults
    if category in _BROADCAST_CATEGORIES:
        return "broadcast"
    if category in _NOTIFY_CATEGORIES:
        return "notify"

    # Rule 5: default
    return "silent"


# ── Debounce buffer (Phase 2) ──

_PROPAGATION_LEVEL = {"silent": 0, "notify": 1, "broadcast": 2}


def debounce_push(pod_url: str, capsule_id: str, propagation: str) -> bool:
    """Push a notification entry to the Zig debounce buffer.

    Returns True if buffered (notify tier), False if broadcast bypass.
    Falls back to immediate delivery if Zig unavailable.
    """
    lib = _get_lib()
    if lib and hasattr(lib, "podos_debounce_push_export"):
        import ctypes
        level = _PROPAGATION_LEVEL.get(propagation, 0)
        result = lib.podos_debounce_push_export(
            pod_url.encode(), len(pod_url),
            capsule_id.encode(), len(capsule_id),
            ctypes.c_uint8(level),
        )
        return result == 1
    # Fallback: no buffering, return False to trigger immediate send
    return False


def debounce_flush(pod_url: str) -> list[str]:
    """Flush pending entries for a pod. Returns list of capsule_ids.

    Falls back to empty list if Zig unavailable.
    """
    lib = _get_lib()
    if lib and hasattr(lib, "podos_debounce_flush_export"):
        import ctypes
        buf = (ctypes.c_char * (64 * 36))()  # 64 entries × 36 bytes each
        count = lib.podos_debounce_flush_export(
            pod_url.encode(), len(pod_url),
            buf, len(buf),
        )
        if count <= 0:
            return []
        capsule_ids = []
        for i in range(count):
            offset = i * 36
            cid = bytes(buf[offset:offset + 36]).decode("utf-8", errors="replace")
            capsule_ids.append(cid)
        return capsule_ids
    return []


def debounce_pending() -> int:
    """Get total pending count across all pod buffers."""
    lib = _get_lib()
    if lib and hasattr(lib, "podos_debounce_pending_export"):
        return lib.podos_debounce_pending_export()
    return 0
