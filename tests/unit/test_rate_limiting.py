"""Tests for rate limiting functionality."""

import pytest
import asyncio
from datetime import datetime, timedelta

from src.exchange_simulator.failures.strategies import (
    FailureContext,
    RateLimitStrategy,
    HardcodedVolumeDetector,
    VolumeDetector,
)
from src.exchange_simulator.rest_api import RateLimiter
from aiohttp import web


@pytest.fixture
def context() -> FailureContext:
    """Create a failure context for testing."""
    return FailureContext(
        session_id="test-session",
        message_type="REST_REQUEST",
        direction="inbound",
    )


class TestHardcodedVolumeDetector:
    """Test cases for HardcodedVolumeDetector."""

    def test_normal_volume(self) -> None:
        """Test normal volume detection."""
        detector = HardcodedVolumeDetector(high_volume=False)
        assert not detector.is_high_volume()
        assert detector.get_volume_multiplier() == 1.0

    def test_high_volume(self) -> None:
        """Test high volume detection."""
        detector = HardcodedVolumeDetector(high_volume=True, volume_multiplier=0.5)
        assert detector.is_high_volume()
        assert detector.get_volume_multiplier() == 0.5

    def test_set_high_volume(self) -> None:
        """Test setting high volume state."""
        detector = HardcodedVolumeDetector(high_volume=False)
        assert not detector.is_high_volume()

        detector.set_high_volume(True)
        assert detector.is_high_volume()
        assert detector.get_volume_multiplier() == 0.5


class TestRateLimitStrategy:
    """Test cases for RateLimitStrategy."""

    async def test_allows_requests_within_limit(self, context: FailureContext) -> None:
        """Test that requests within limit are allowed."""
        strategy = RateLimitStrategy(baseline_rps=10, wait_period_seconds=1)

        for i in range(10):
            result = await strategy.apply("test", context)
            assert result == "test"

    async def test_rate_limits_exceeding_baseline(self, context: FailureContext) -> None:
        """Test that exceeding baseline rate is limited."""
        strategy = RateLimitStrategy(baseline_rps=5, wait_period_seconds=1)

        allowed = 0
        for i in range(10):
            result = await strategy.apply("test", context)
            if result is not None:
                allowed += 1

        assert allowed == 5
        assert strategy.rate_limited_count > 0

    async def test_first_violation_wait_period(self, context: FailureContext) -> None:
        """Test first violation triggers wait period."""
        strategy = RateLimitStrategy(
            baseline_rps=2, wait_period_seconds=1, violation_window_seconds=60
        )

        session_id = context.session_id

        for i in range(3):
            await strategy.apply("test", context)

        allowed, error, retry_after = await strategy._check_rate_limit(session_id)
        assert not allowed
        assert retry_after == 1

    async def test_second_violation_longer_ban(self, context: FailureContext) -> None:
        """Test second violation triggers longer ban."""
        strategy = RateLimitStrategy(
            baseline_rps=2,
            wait_period_seconds=1,
            second_violation_ban_seconds=60,
            violation_window_seconds=60,
        )

        session_id = context.session_id

        for _ in range(3):
            await strategy.apply("test", context)

        await asyncio.sleep(1.1)

        for _ in range(3):
            await strategy.apply("test", context)

        allowed, error, retry_after = await strategy._check_rate_limit(session_id)
        assert not allowed
        assert retry_after == 60

    async def test_third_violation_permanent_ban(self, context: FailureContext) -> None:
        """Test third violation results in permanent ban."""
        strategy = RateLimitStrategy(
            baseline_rps=2,
            wait_period_seconds=1,
            second_violation_ban_seconds=1,
            violation_window_seconds=60,
        )

        session_id = context.session_id

        for violation in range(3):
            for _ in range(3):
                await strategy.apply("test", context)
            await asyncio.sleep(1.1)

        await asyncio.sleep(1.1)

        allowed, error, retry_after = await strategy._check_rate_limit(session_id)
        assert not allowed
        assert retry_after is None
        assert "permanently banned" in error.lower()
        assert session_id in strategy._permanent_bans

    async def test_high_volume_reduces_limit(self, context: FailureContext) -> None:
        """Test that high volume reduces rate limit."""
        volume_detector = HardcodedVolumeDetector(high_volume=True, volume_multiplier=0.5)
        strategy = RateLimitStrategy(
            baseline_rps=10, wait_period_seconds=1, volume_detector=volume_detector
        )

        allowed = 0
        for i in range(10):
            result = await strategy.apply("test", context)
            if result is not None:
                allowed += 1

        assert allowed == 5

    async def test_violation_count_tracking(self, context: FailureContext) -> None:
        """Test violation count tracking."""
        strategy = RateLimitStrategy(baseline_rps=2, wait_period_seconds=1)

        session_id = context.session_id

        for _ in range(3):
            await strategy.apply("test", context)

        count = strategy.get_violation_count(session_id)
        assert count == 1

    async def test_reset_clears_state(self, context: FailureContext) -> None:
        """Test reset clears all state."""
        strategy = RateLimitStrategy(baseline_rps=2, wait_period_seconds=1)

        for _ in range(3):
            await strategy.apply("test", context)

        await strategy.reset_async()

        result = await strategy.apply("test", context)
        assert result == "test"
        assert strategy.rate_limited_count == 0

    async def test_sliding_window(self, context: FailureContext) -> None:
        """Test that sliding window allows requests after time passes."""
        strategy = RateLimitStrategy(baseline_rps=5, wait_period_seconds=1)

        for i in range(5):
            result = await strategy.apply("test", context)
            assert result == "test"

        result = await strategy.apply("test", context)
        assert result is None

        await asyncio.sleep(1.1)

        result = await strategy.apply("test", context)
        assert result == "test"

    def test_invalid_parameters(self) -> None:
        """Test that invalid parameters raise errors."""
        with pytest.raises(ValueError):
            RateLimitStrategy(baseline_rps=0)

        with pytest.raises(ValueError):
            RateLimitStrategy(baseline_rps=10, wait_period_seconds=-1)

        with pytest.raises(ValueError):
            RateLimitStrategy(
                baseline_rps=10, wait_period_seconds=10, second_violation_ban_seconds=-1
            )

    async def test_get_stats(self, context: FailureContext) -> None:
        """Test statistics collection."""
        strategy = RateLimitStrategy(baseline_rps=2, wait_period_seconds=1)

        for _ in range(3):
            await strategy.apply("test", context)

        stats = strategy.get_stats()
        assert "rate_limited_count" in stats
        assert "banned_sessions" in stats
        assert "permanent_bans" in stats


class TestRateLimiter:
    """Test cases for RateLimiter middleware."""

    async def test_allows_when_no_strategy(self) -> None:
        """Test that requests are allowed when no strategy is set."""
        limiter = RateLimiter(rate_limit_strategy=None)
        await limiter.check_rate_limit("test-session", "/api/v1/orders")

    async def test_raises_429_when_rate_limited(self, context: FailureContext) -> None:
        """Test that rate limiter raises HTTP 429 when rate limited."""
        strategy = RateLimitStrategy(baseline_rps=2, wait_period_seconds=10)
        limiter = RateLimiter(rate_limit_strategy=strategy)

        for _ in range(2):
            await limiter.check_rate_limit("test-session", "/api/v1/orders")

        with pytest.raises(web.HTTPTooManyRequests) as exc_info:
            await limiter.check_rate_limit("test-session", "/api/v1/orders")

        assert exc_info.value.status == 429

    async def test_429_response_includes_retry_after(self, context: FailureContext) -> None:
        """Test that 429 response includes Retry-After header."""
        strategy = RateLimitStrategy(baseline_rps=2, wait_period_seconds=10)
        limiter = RateLimiter(rate_limit_strategy=strategy)

        for _ in range(2):
            await limiter.check_rate_limit("test-session", "/api/v1/orders")

        with pytest.raises(web.HTTPTooManyRequests) as exc_info:
            await limiter.check_rate_limit("test-session", "/api/v1/orders")

        assert exc_info.value.status == 429
        assert "Retry-After" in exc_info.value.headers
        assert exc_info.value.headers["Retry-After"] == "10"

    async def test_429_response_includes_error_details(self, context: FailureContext) -> None:
        """Test that 429 response includes error details."""
        strategy = RateLimitStrategy(baseline_rps=2, wait_period_seconds=10)
        limiter = RateLimiter(rate_limit_strategy=strategy)

        for _ in range(2):
            await limiter.check_rate_limit("test-session", "/api/v1/orders")

        with pytest.raises(web.HTTPTooManyRequests) as exc_info:
            await limiter.check_rate_limit("test-session", "/api/v1/orders")

        assert exc_info.value.status == 429
        assert "error" in str(exc_info.value.text).lower() or "rate limit" in str(exc_info.value.text).lower()

