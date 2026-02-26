"""
Spark Rate Limiter — In-memory sliding window.

Keyed by client_id:ip. Resets on deploy/crash (known MVP limitation).
Redis-backed implementation planned for v2.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class SparkRateLimiter:
    """Sliding window rate limiter for Spark endpoints."""

    def __init__(self) -> None:
        # key -> list of request timestamps
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, client_id: str, ip: str, rpm_limit: int) -> bool:
        """Check if request is allowed. Returns True if allowed, False if blocked."""
        key = f"{client_id}:{ip}"
        now = time.monotonic()
        window_start = now - 60.0

        # Prune expired entries
        timestamps = self._windows[key]
        self._windows[key] = [t for t in timestamps if t > window_start]

        if len(self._windows[key]) >= rpm_limit:
            logger.warning("Spark rate limit hit: %s (%d RPM)", key, rpm_limit)
            return False

        self._windows[key].append(now)
        return True

    def reset(self) -> None:
        """Clear all windows (for testing)."""
        self._windows.clear()


# Singleton
_rate_limiter: SparkRateLimiter | None = None


def get_rate_limiter() -> SparkRateLimiter:
    """Get or create the singleton rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = SparkRateLimiter()
    return _rate_limiter


def reset_rate_limiter() -> None:
    """Reset the singleton (for testing)."""
    global _rate_limiter
    _rate_limiter = None
