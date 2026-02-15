"""Application-level rate limiting for solicitation abuse prevention.

This is NOT Citadel (which is a text guard). This is separate, application-level
protection against mass-befriending, query spam, and scraping.
"""

import time
from collections import defaultdict


class SlidingWindowCounter:
    """Simple sliding window counter using in-memory storage.

    Production: replace with Redis ZRANGEBYSCORE.
    """

    def __init__(self):
        self._events: dict[str, list[float]] = defaultdict(list)

    def record(self, key: str) -> None:
        """Record an event."""
        self._events[key].append(time.time())

    def count(self, key: str, window_seconds: int) -> int:
        """Count events in the last N seconds."""
        cutoff = time.time() - window_seconds
        events = self._events[key]
        # Prune old events
        self._events[key] = [t for t in events if t > cutoff]
        return len(self._events[key])

    def reset(self) -> None:
        """Clear all tracked events (primarily for tests)."""
        self._events.clear()


# Global rate limiter instances
_connection_limiter = SlidingWindowCounter()
_query_limiter = SlidingWindowCounter()


def check_connection_rate(user_id: str) -> tuple[bool, str]:
    """Check if user can send a connection request.

    Limits:
    - 10 requests per day (86400s)
    - 30 per week (604800s)
    """
    daily = _connection_limiter.count(f"conn:{user_id}:day", 86400)
    if daily >= 10:
        return False, "Daily connection request limit reached (10/day). Try again tomorrow."

    weekly = _connection_limiter.count(f"conn:{user_id}:week", 604800)
    if weekly >= 30:
        return False, "Weekly connection request limit reached (30/week)."

    return True, "ok"


def record_connection_request(user_id: str) -> None:
    """Record a connection request for rate limiting."""
    _connection_limiter.record(f"conn:{user_id}:day")
    _connection_limiter.record(f"conn:{user_id}:week")


def check_query_rate(user_id: str, target_id: str, trust_level: str) -> tuple[bool, str]:
    """Check if user can send a query.

    Limits:
    - 5 queries per minute (burst)
    - 20 queries per hour to same target
    - 100 queries per day total
    - Public-tier: 5/hour to same target, 20/day total
    """
    # Burst limit
    burst = _query_limiter.count(f"query:{user_id}:burst", 60)
    if burst >= 5:
        return False, "Too many queries. Please wait a minute."

    # Per-target hourly
    per_target = _query_limiter.count(f"query:{user_id}:{target_id}:hour", 3600)
    if trust_level == "public":
        if per_target >= 5:
            return False, "Query limit reached for this user (5/hour for public access)."
    else:
        if per_target >= 20:
            return False, "Query limit reached for this user (20/hour)."

    # Daily total
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
    _query_limiter.record(f"query:{user_id}:burst")
    _query_limiter.record(f"query:{user_id}:{target_id}:hour")
    _query_limiter.record(f"query:{user_id}:day")


def reset_rate_limits() -> None:
    """Reset all in-memory rate limit state (test helper)."""
    _connection_limiter.reset()
    _query_limiter.reset()
