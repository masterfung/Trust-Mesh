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
