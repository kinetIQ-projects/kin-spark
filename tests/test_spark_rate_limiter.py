"""
Tests for Spark Rate Limiter.

Covers: allow under limit, block over limit, window expiry.
"""

import time
from unittest.mock import patch

import pytest

from app.services.spark.rate_limiter import SparkRateLimiter

# ===========================================================================
# TestSparkRateLimiter
# ===========================================================================


@pytest.mark.unit
class TestSparkRateLimiter:
    """In-memory sliding window rate limiter."""

    def test_allows_under_limit(self) -> None:
        limiter = SparkRateLimiter()
        for _ in range(5):
            assert limiter.check("client-1", "1.2.3.4", rpm_limit=10) is True

    def test_blocks_over_limit(self) -> None:
        limiter = SparkRateLimiter()
        for _ in range(10):
            limiter.check("client-1", "1.2.3.4", rpm_limit=10)
        assert limiter.check("client-1", "1.2.3.4", rpm_limit=10) is False

    def test_different_ips_have_separate_windows(self) -> None:
        limiter = SparkRateLimiter()
        for _ in range(10):
            limiter.check("client-1", "1.2.3.4", rpm_limit=10)
        # Different IP should still be allowed
        assert limiter.check("client-1", "5.6.7.8", rpm_limit=10) is True

    def test_different_clients_have_separate_windows(self) -> None:
        limiter = SparkRateLimiter()
        for _ in range(10):
            limiter.check("client-1", "1.2.3.4", rpm_limit=10)
        # Different client should still be allowed
        assert limiter.check("client-2", "1.2.3.4", rpm_limit=10) is True

    def test_window_expiry_allows_new_requests(self) -> None:
        limiter = SparkRateLimiter()
        # Fill the window
        now = time.monotonic()
        for _ in range(10):
            limiter.check("client-1", "1.2.3.4", rpm_limit=10)

        # Simulate time passing (> 60 seconds)
        with patch("app.services.spark.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = now + 61.0
            assert limiter.check("client-1", "1.2.3.4", rpm_limit=10) is True

    def test_reset_clears_all_windows(self) -> None:
        limiter = SparkRateLimiter()
        for _ in range(10):
            limiter.check("client-1", "1.2.3.4", rpm_limit=10)
        assert limiter.check("client-1", "1.2.3.4", rpm_limit=10) is False

        limiter.reset()
        assert limiter.check("client-1", "1.2.3.4", rpm_limit=10) is True

    def test_exact_limit_still_allowed(self) -> None:
        limiter = SparkRateLimiter()
        for i in range(10):
            result = limiter.check("client-1", "1.2.3.4", rpm_limit=10)
            assert result is True, f"Request {i+1} should be allowed"
        # 11th should be blocked
        assert limiter.check("client-1", "1.2.3.4", rpm_limit=10) is False
