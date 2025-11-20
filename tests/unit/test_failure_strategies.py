"""Tests for failure strategies."""

import pytest
import asyncio
import time
from decimal import Decimal

from src.exchange_simulator.failures.strategies import (
    FailureContext,
    DropMessageStrategy,
    DelayMessageStrategy,
    DuplicateMessageStrategy,
    ReorderMessagesStrategy,
    CorruptMessageStrategy,
    ThrottleMessageStrategy,
)


@pytest.fixture
def context() -> FailureContext:
    """Create a failure context for testing."""
    return FailureContext(
        session_id="SESSION1",
        message_type="PLACE_ORDER",
        direction="inbound",
    )


class TestDropMessageStrategy:
    """Test cases for DropMessageStrategy."""

    async def test_drop_never(self, context: FailureContext) -> None:
        """Test that messages are never dropped with 0% probability."""
        strategy = DropMessageStrategy(probability=0.0)

        for _ in range(100):
            result = await strategy.apply("test message", context)
            assert result == "test message"

        assert strategy.get_stats()["dropped_count"] == 0

    async def test_drop_always(self, context: FailureContext) -> None:
        """Test that messages are always dropped with 100% probability."""
        strategy = DropMessageStrategy(probability=1.0)

        for _ in range(100):
            result = await strategy.apply("test message", context)
            assert result is None

        assert strategy.get_stats()["dropped_count"] == 100

    async def test_drop_probabilistic(self, context: FailureContext) -> None:
        """Test that messages are dropped with approximate probability."""
        strategy = DropMessageStrategy(probability=0.5)
        iterations = 1000

        dropped = 0
        for _ in range(iterations):
            result = await strategy.apply("test message", context)
            if result is None:
                dropped += 1

        # Check that drop rate is approximately 50% (with 10% tolerance)
        assert 0.4 <= dropped / iterations <= 0.6
        assert strategy.get_stats()["dropped_count"] == dropped

    async def test_reset(self, context: FailureContext) -> None:
        """Test resetting strategy statistics."""
        strategy = DropMessageStrategy(probability=1.0)

        await strategy.apply("test", context)
        assert strategy.get_stats()["dropped_count"] == 1

        strategy.reset()
        assert strategy.get_stats()["dropped_count"] == 0

    def test_invalid_probability(self) -> None:
        """Test that invalid probability raises error."""
        with pytest.raises(ValueError):
            DropMessageStrategy(probability=-0.1)

        with pytest.raises(ValueError):
            DropMessageStrategy(probability=1.5)


class TestDelayMessageStrategy:
    """Test cases for DelayMessageStrategy."""

    async def test_adds_delay(self, context: FailureContext) -> None:
        """Test that delay is added to messages."""
        strategy = DelayMessageStrategy(min_ms=50, max_ms=100)

        start = time.time()
        result = await strategy.apply("test message", context)
        elapsed = (time.time() - start) * 1000

        assert result == "test message"
        assert 50 <= elapsed <= 150  # Allow some overhead

    async def test_delay_range(self, context: FailureContext) -> None:
        """Test that delay is within specified range."""
        strategy = DelayMessageStrategy(min_ms=10, max_ms=20)
        iterations = 100

        delays = []
        for _ in range(iterations):
            start = time.time()
            await strategy.apply("test", context)
            elapsed = (time.time() - start) * 1000
            delays.append(elapsed)

        # All delays should be roughly within range
        assert all(5 <= d <= 30 for d in delays)  # Allow overhead

    async def test_statistics(self, context: FailureContext) -> None:
        """Test delay statistics."""
        strategy = DelayMessageStrategy(min_ms=50, max_ms=100)

        for _ in range(10):
            await strategy.apply("test", context)

        stats = strategy.get_stats()
        assert stats["delayed_count"] == 10
        assert 50 <= stats["average_delay_ms"] <= 100

    async def test_reset(self, context: FailureContext) -> None:
        """Test resetting strategy statistics."""
        strategy = DelayMessageStrategy(min_ms=10, max_ms=20)

        await strategy.apply("test", context)
        strategy.reset()

        stats = strategy.get_stats()
        assert stats["delayed_count"] == 0
        assert stats["total_delay_ms"] == 0

    def test_invalid_delays(self) -> None:
        """Test that invalid delays raise errors."""
        with pytest.raises(ValueError):
            DelayMessageStrategy(min_ms=-1, max_ms=100)

        with pytest.raises(ValueError):
            DelayMessageStrategy(min_ms=100, max_ms=50)


class TestDuplicateMessageStrategy:
    """Test cases for DuplicateMessageStrategy."""

    async def test_no_duplication(self, context: FailureContext) -> None:
        """Test that messages are not duplicated with 0% probability."""
        strategy = DuplicateMessageStrategy(probability=0.0)

        for _ in range(100):
            result = await strategy.apply("test message", context)
            assert result == "test message"

        assert strategy.get_stats()["duplicated_count"] == 0

    async def test_always_duplicate(self, context: FailureContext) -> None:
        """Test that messages are always duplicated with 100% probability."""
        strategy = DuplicateMessageStrategy(probability=1.0, max_duplicates=2)

        # Process several messages
        messages_received = []
        for i in range(5):
            # Each message should generate the original plus pending duplicates
            result = await strategy.apply(f"message{i}", context)
            messages_received.append(result)

            # Get pending duplicates
            while True:
                dup = await strategy.apply(f"message{i+1}", context)
                if not dup or dup.startswith(f"message{i+1}"):
                    messages_received.append(dup)
                    break
                messages_received.append(dup)

        # We should have received duplicates
        assert strategy.get_stats()["duplicated_count"] > 0

    async def test_reset(self, context: FailureContext) -> None:
        """Test resetting strategy statistics."""
        strategy = DuplicateMessageStrategy(probability=1.0, max_duplicates=2)

        await strategy.apply("test", context)
        strategy.reset()

        assert strategy.get_stats()["duplicated_count"] == 0

    def test_invalid_parameters(self) -> None:
        """Test that invalid parameters raise errors."""
        with pytest.raises(ValueError):
            DuplicateMessageStrategy(probability=-0.1)

        with pytest.raises(ValueError):
            DuplicateMessageStrategy(probability=0.5, max_duplicates=0)


class TestReorderMessagesStrategy:
    """Test cases for ReorderMessagesStrategy."""

    async def test_buffers_messages(self, context: FailureContext) -> None:
        """Test that messages are buffered."""
        strategy = ReorderMessagesStrategy(window_size=3)

        # First messages should be buffered (return None)
        result1 = await strategy.apply("msg1", context)
        result2 = await strategy.apply("msg2", context)

        assert result1 is None
        assert result2 is None
        assert strategy.get_stats()["buffered_count"] == 2

    async def test_delivers_after_window_full(self, context: FailureContext) -> None:
        """Test that messages are delivered after window is full."""
        strategy = ReorderMessagesStrategy(window_size=3)

        results = []
        for i in range(5):
            result = await strategy.apply(f"msg{i}", context)
            if result is not None:
                results.append(result)

        # Should have delivered 3 messages (5 sent - 2 buffered at end)
        # Window fills at msg2 (0,1,2), then starts delivering
        assert len(results) == 3

    async def test_flush(self, context: FailureContext) -> None:
        """Test flushing buffered messages."""
        strategy = ReorderMessagesStrategy(window_size=3)

        await strategy.apply("msg1", context)
        await strategy.apply("msg2", context)

        flushed = strategy.flush()
        assert len(flushed) == 2
        assert strategy.get_stats()["buffered_count"] == 0

    async def test_reset(self, context: FailureContext) -> None:
        """Test resetting strategy statistics."""
        strategy = ReorderMessagesStrategy(window_size=3)

        for i in range(5):
            await strategy.apply(f"msg{i}", context)

        strategy.reset()
        assert strategy.get_stats()["reordered_count"] == 0
        assert strategy.get_stats()["buffered_count"] == 0

    def test_invalid_window_size(self) -> None:
        """Test that invalid window size raises error."""
        with pytest.raises(ValueError):
            ReorderMessagesStrategy(window_size=1)


class TestCorruptMessageStrategy:
    """Test cases for CorruptMessageStrategy."""

    async def test_no_corruption(self, context: FailureContext) -> None:
        """Test that messages are not corrupted with 0% probability."""
        strategy = CorruptMessageStrategy(probability=0.0)

        for _ in range(100):
            result = await strategy.apply("test message", context)
            assert result == "test message"

        assert strategy.get_stats()["corrupted_count"] == 0

    async def test_always_corrupt(self, context: FailureContext) -> None:
        """Test that messages are always corrupted with 100% probability."""
        strategy = CorruptMessageStrategy(probability=1.0)

        for _ in range(100):
            result = await strategy.apply("test message", context)
            assert result != "test message"  # Should be corrupted
            assert len(result) == len("test message")  # Same length

        assert strategy.get_stats()["corrupted_count"] == 100

    async def test_corruption_level(self, context: FailureContext) -> None:
        """Test corruption level affects number of changed characters."""
        strategy_low = CorruptMessageStrategy(probability=1.0, corruption_level=0.1)
        strategy_high = CorruptMessageStrategy(probability=1.0, corruption_level=0.5)

        message = "a" * 100

        result_low = await strategy_low.apply(message, context)
        result_high = await strategy_high.apply(message, context)

        # Count differences
        diff_low = sum(1 for a, b in zip(message, result_low) if a != b)
        diff_high = sum(1 for a, b in zip(message, result_high) if a != b)

        # Higher corruption level should corrupt more characters
        assert diff_high > diff_low

    async def test_reset(self, context: FailureContext) -> None:
        """Test resetting strategy statistics."""
        strategy = CorruptMessageStrategy(probability=1.0)

        await strategy.apply("test", context)
        strategy.reset()

        assert strategy.get_stats()["corrupted_count"] == 0

    def test_invalid_parameters(self) -> None:
        """Test that invalid parameters raise errors."""
        with pytest.raises(ValueError):
            CorruptMessageStrategy(probability=-0.1)

        with pytest.raises(ValueError):
            CorruptMessageStrategy(probability=0.5, corruption_level=0.0)

        with pytest.raises(ValueError):
            CorruptMessageStrategy(probability=0.5, corruption_level=1.5)


class TestThrottleMessageStrategy:
    """Test cases for ThrottleMessageStrategy."""

    async def test_throttles_rate(self, context: FailureContext) -> None:
        """Test that message rate is throttled."""
        strategy = ThrottleMessageStrategy(max_messages_per_second=10)
        iterations = 20

        start = time.time()
        for _ in range(iterations):
            await strategy.apply("test", context)
        elapsed = time.time() - start

        # Should take approximately 2 seconds (20 messages at 10/sec)
        assert 1.8 <= elapsed <= 2.5  # Allow some overhead

    async def test_statistics(self, context: FailureContext) -> None:
        """Test throttle statistics."""
        strategy = ThrottleMessageStrategy(max_messages_per_second=100)

        for _ in range(10):
            await strategy.apply("test", context)

        stats = strategy.get_stats()
        assert stats["throttled_count"] >= 0  # Some messages may be throttled

    async def test_reset(self, context: FailureContext) -> None:
        """Test resetting strategy statistics."""
        strategy = ThrottleMessageStrategy(max_messages_per_second=10)

        for _ in range(5):
            await strategy.apply("test", context)

        strategy.reset()
        assert strategy.get_stats()["throttled_count"] == 0

    def test_invalid_rate(self) -> None:
        """Test that invalid rate raises error."""
        with pytest.raises(ValueError):
            ThrottleMessageStrategy(max_messages_per_second=0)

        with pytest.raises(ValueError):
            ThrottleMessageStrategy(max_messages_per_second=-10)
