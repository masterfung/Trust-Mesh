"""Application-level rate limiting — backed by Zig libpodos sliding window counters.

Replaces in-memory Python SlidingWindowCounter with Zig's native implementation.
Falls back to Python if Zig is not initialized (e.g., in test fixtures).
"""

import ctypes
import time
from collections import defaultdict
from ctypes import c_uint32

_zig_initialized = False


def _get_lib():
    from src.timeline_bridge import _get_lib as _tl_get_lib
    return _tl_get_lib()


def _ensure_zig():
    """Ensure Zig rate limiter is initialized (lazy init)."""
    global _zig_initialized
    if not _zig_initialized:
        try:
            lib = _get_lib()
            rc = lib.podos_rate_init()
            _zig_initialized = (rc == 0)
        except Exception:
            pass


def _init_rate_limits():
    """Initialize the Zig rate limiter. Called once on startup."""
    global _zig_initialized
    lib = _get_lib()
    rc = lib.podos_rate_init()
    if rc != 0:
        raise RuntimeError("Failed to initialize rate limiter")
    _zig_initialized = True


def _deinit_rate_limits():
    """Destroy the Zig rate limiter. Called on shutdown."""
    global _zig_initialized
    lib = _get_lib()
    lib.podos_rate_deinit()
    _zig_initialized = False


class SlidingWindowCounter:
    """Backward-compat Python fallback. Used when Zig is not initialized."""

    def __init__(self):
        self._events: dict[str, list[float]] = defaultdict(list)

    def record(self, key: str) -> None:
        self._events[key].append(time.time())

    def count(self, key: str, window_seconds: int) -> int:
        cutoff = time.time() - window_seconds
        events = self._events[key]
        self._events[key] = [t for t in events if t > cutoff]
        return len(self._events[key])

    def reset(self) -> None:
        self._events.clear()


# Global rate limiter instances (Python fallback + backward-compat for test imports)
_connection_limiter = SlidingWindowCounter()
_query_limiter = SlidingWindowCounter()

# PIN rate limiting (Python-only, no Zig backend needed)
_pin_attempts: dict[str, list[float]] = defaultdict(list)
PIN_MAX_ATTEMPTS = 5
PIN_WINDOW = 900  # 15 minutes

# Emergency rate limiting
_emergency_issue_limiter = SlidingWindowCounter()
_emergency_present_limiter = SlidingWindowCounter()
EMERGENCY_ISSUE_MAX = 3   # per hour per issuer:patient pair
EMERGENCY_ISSUE_WINDOW = 3600
EMERGENCY_PRESENT_MAX = 5  # per hour per token hash
EMERGENCY_PRESENT_WINDOW = 3600


def check_connection_rate(user_id: str) -> tuple[bool, str]:
    """Check if user can send a connection request."""
    _ensure_zig()
    if _zig_initialized:
        lib = _get_lib()
        uid = user_id.encode("utf-8")
        out_msg = ctypes.create_string_buffer(256)
        out_len = c_uint32(0)
        result = lib.podos_rate_check_connection(uid, len(uid), out_msg, ctypes.byref(out_len))
        if result >= 0:
            msg = out_msg.raw[:out_len.value].decode("utf-8") if out_len.value > 0 else "ok"
            return result == 1, msg

    # Fallback: Python implementation
    daily = _connection_limiter.count(f"conn:{user_id}:day", 86400)
    if daily >= 10:
        return False, "Daily connection request limit reached (10/day). Try again tomorrow."
    weekly = _connection_limiter.count(f"conn:{user_id}:week", 604800)
    if weekly >= 30:
        return False, "Weekly connection request limit reached (30/week)."
    return True, "ok"


def record_connection_request(user_id: str) -> None:
    """Record a connection request for rate limiting."""
    _ensure_zig()
    if _zig_initialized:
        lib = _get_lib()
        uid = user_id.encode("utf-8")
        lib.podos_rate_record_connection(uid, len(uid))
        return
    _connection_limiter.record(f"conn:{user_id}:day")
    _connection_limiter.record(f"conn:{user_id}:week")


def check_query_rate(user_id: str, target_id: str, trust_level: str) -> tuple[bool, str]:
    """Check if user can send a query."""
    _ensure_zig()
    if _zig_initialized:
        lib = _get_lib()
        uid = user_id.encode("utf-8")
        tid = target_id.encode("utf-8")
        is_public = 1 if trust_level == "public" else 0
        out_msg = ctypes.create_string_buffer(256)
        out_len = c_uint32(0)
        result = lib.podos_rate_check_query(
            uid, len(uid), tid, len(tid), is_public, out_msg, ctypes.byref(out_len)
        )
        if result >= 0:
            msg = out_msg.raw[:out_len.value].decode("utf-8") if out_len.value > 0 else "ok"
            return result == 1, msg

    # Fallback: Python implementation
    burst = _query_limiter.count(f"query:{user_id}:burst", 60)
    if burst >= 5:
        return False, "Too many queries. Please wait a minute."
    per_target = _query_limiter.count(f"query:{user_id}:{target_id}:hour", 3600)
    if trust_level == "public":
        if per_target >= 5:
            return False, "Query limit reached for this user (5/hour for public access)."
    else:
        if per_target >= 20:
            return False, "Query limit reached for this user (20/hour)."
    daily = _query_limiter.count(f"query:{user_id}:day", 86400)
    if trust_level == "public":
        if daily >= 20:
            return False, "Daily query limit reached (20/day for public access)."
    else:
        if daily >= 100:
            return False, "Daily query limit reached (100/day)."
    return True, "ok"


def record_query(user_id: str, target_id: str) -> None:
    """Record a query for rate limiting."""
    _ensure_zig()
    if _zig_initialized:
        lib = _get_lib()
        uid = user_id.encode("utf-8")
        tid = target_id.encode("utf-8")
        lib.podos_rate_record_query(uid, len(uid), tid, len(tid))
        return
    _query_limiter.record(f"query:{user_id}:burst")
    _query_limiter.record(f"query:{user_id}:{target_id}:hour")
    _query_limiter.record(f"query:{user_id}:day")


def check_pin_rate(user_id: str) -> tuple[bool, str]:
    """Check if user has exceeded PIN attempt limit."""
    now = time.time()
    window_start = now - PIN_WINDOW
    attempts = [t for t in _pin_attempts[user_id] if t > window_start]
    _pin_attempts[user_id] = attempts
    if len(attempts) >= PIN_MAX_ATTEMPTS:
        return False, "Too many PIN attempts. Try again in 15 minutes."
    return True, ""


def record_pin_attempt(user_id: str) -> None:
    """Record a PIN verification attempt."""
    _pin_attempts[user_id].append(time.time())


def check_emergency_issue_rate(key: str) -> tuple[bool, str]:
    """Check if emergency token issuance is allowed for this issuer:patient pair."""
    _ensure_zig()
    if _zig_initialized:
        lib = _get_lib()
        k = key.encode("utf-8")
        out_msg = ctypes.create_string_buffer(256)
        out_len = c_uint32(0)
        result = lib.podos_rate_check_emergency_issue(k, len(k), out_msg, ctypes.byref(out_len))
        if result >= 0:
            msg = out_msg.raw[:out_len.value].decode("utf-8") if out_len.value > 0 else "ok"
            return result == 1, msg

    # Fallback
    count = _emergency_issue_limiter.count(key, EMERGENCY_ISSUE_WINDOW)
    if count >= EMERGENCY_ISSUE_MAX:
        return False, "Emergency token issuance limit reached (3/hour per patient)."
    return True, "ok"


def record_emergency_issue(key: str) -> None:
    """Record an emergency token issuance."""
    _ensure_zig()
    if _zig_initialized:
        lib = _get_lib()
        k = key.encode("utf-8")
        lib.podos_rate_record_emergency_issue(k, len(k))
        return
    _emergency_issue_limiter.record(key)


def check_emergency_present_rate(key: str) -> tuple[bool, str]:
    """Check if emergency access is allowed for this token hash."""
    _ensure_zig()
    if _zig_initialized:
        lib = _get_lib()
        k = key.encode("utf-8")
        out_msg = ctypes.create_string_buffer(256)
        out_len = c_uint32(0)
        result = lib.podos_rate_check_emergency_present(k, len(k), out_msg, ctypes.byref(out_len))
        if result >= 0:
            msg = out_msg.raw[:out_len.value].decode("utf-8") if out_len.value > 0 else "ok"
            return result == 1, msg

    # Fallback
    count = _emergency_present_limiter.count(key, EMERGENCY_PRESENT_WINDOW)
    if count >= EMERGENCY_PRESENT_MAX:
        return False, "Emergency access limit reached. Token has been used too many times."
    return True, "ok"


def record_emergency_present(key: str) -> None:
    """Record an emergency access attempt."""
    _ensure_zig()
    if _zig_initialized:
        lib = _get_lib()
        k = key.encode("utf-8")
        lib.podos_rate_record_emergency_present(k, len(k))
        return
    _emergency_present_limiter.record(key)


def reset_rate_limits() -> None:
    """Reset all in-memory rate limit state (test helper)."""
    _connection_limiter.reset()
    _query_limiter.reset()
    _pin_attempts.clear()
    _emergency_issue_limiter.reset()
    _emergency_present_limiter.reset()
    if _zig_initialized:
        try:
            lib = _get_lib()
            lib.podos_rate_reset()
        except Exception:
            pass
