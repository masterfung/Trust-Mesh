"""Bridge to Zig research cache + freshness scoring (libpodos).

Falls back to pure Python when the Zig kernel is not compiled yet.
Follows the same pattern as credential_bridge and timeline_bridge.
"""
import ctypes
import hashlib
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

_lib = None
_lib_loaded = False


def _get_lib():
    global _lib, _lib_loaded
    if _lib_loaded:
        return _lib
    _lib_loaded = True
    kernel_dir = Path(__file__).parent.parent / "kernel"
    lib_name = "libpodos.dylib" if os.uname().sysname == "Darwin" else "libpodos.so"
    lib_path = kernel_dir / "zig-out" / "lib" / lib_name
    if not lib_path.exists():
        log.debug("research_bridge: Zig kernel not found at %s — using Python fallback", lib_path)
        return None
    try:
        lib = ctypes.CDLL(str(lib_path))
        lib.podos_research_cache_get.argtypes = [
            ctypes.c_char_p, ctypes.c_uint32,
            ctypes.c_char_p, ctypes.c_uint32,
            ctypes.c_int64,
            ctypes.c_char_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        lib.podos_research_cache_get.restype = ctypes.c_int32
        lib.podos_research_cache_put.argtypes = [
            ctypes.c_char_p, ctypes.c_uint32,
            ctypes.c_char_p, ctypes.c_uint32,
            ctypes.c_char_p, ctypes.c_uint32,
            ctypes.c_int64,
        ]
        lib.podos_research_cache_put.restype = ctypes.c_int32
        lib.podos_freshness_score.argtypes = [
            ctypes.c_uint8, ctypes.c_int32, ctypes.c_float,
        ]
        lib.podos_freshness_score.restype = ctypes.c_float
        _lib = lib
        log.debug("research_bridge: loaded Zig kernel from %s", lib_path)
        return lib
    except Exception as e:
        log.warning("research_bridge: failed to load Zig kernel: %s — using Python fallback", e)
        return None


# Python fallback cache: key → (result_str, timestamp, ttl_secs)
_py_cache: dict[str, tuple[str, float, int]] = {}


def cache_get(url: str, goal: str, max_age_secs: int = 7 * 86400) -> str | None:
    """Return cached TinyFish result for url+goal, or None on miss/expiry."""
    lib = _get_lib()
    if lib:
        out = ctypes.create_string_buffer(1 << 17)  # 128 KB
        out_len = ctypes.c_uint32(0)
        u, g = url.encode(), goal.encode()
        rc = lib.podos_research_cache_get(
            u, len(u), g, len(g),
            max_age_secs,
            out, len(out), ctypes.byref(out_len),
        )
        if rc == 0:
            return out.raw[: out_len.value].decode()
        return None
    # Python fallback
    key = hashlib.sha256(f"{url}::{goal}".encode()).hexdigest()
    if key in _py_cache:
        result, ts, ttl = _py_cache[key]
        if time.time() - ts < min(ttl, max_age_secs):
            return result
    return None


def cache_put(url: str, goal: str, result: str, ttl_secs: int = 7 * 86400) -> None:
    """Store a TinyFish result in the cache."""
    lib = _get_lib()
    if lib:
        u, g, r = url.encode(), goal.encode(), result.encode()
        lib.podos_research_cache_put(u, len(u), g, len(g), r, len(r), ttl_secs)
        return
    # Python fallback
    key = hashlib.sha256(f"{url}::{goal}".encode()).hexdigest()
    _py_cache[key] = (result, time.time(), ttl_secs)


def freshness_score(
    freshness_type: str, days_since_verified: int, authority_weight: float
) -> float:
    """Composite freshness score [0.0, 1.0] — higher = fresher + higher authority."""
    lib = _get_lib()
    if lib:
        t = {"permanent": 0, "temporary": 1, "recurring": 2}.get(freshness_type, 0)
        return float(lib.podos_freshness_score(t, days_since_verified, authority_weight))
    # Python fallback
    d = float(days_since_verified)
    recency = {
        "permanent": 1.0,
        "temporary": max(0.0, 1.0 - d / 30.0),
        "recurring": max(0.0, 1.0 - d / 7.0),
    }.get(freshness_type, 0.5)
    return recency * min(authority_weight, 2.0) * 0.5
