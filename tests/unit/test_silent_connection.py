"""Tests for silent connection failure strategy."""

import pytest
from src.exchange_simulator.failures.strategies import (
    SilentConnectionStrategy,
    FailureContext,
)


class TestSilentConnectionStrategy:
    """Test cases for SilentConnectionStrategy."""

    @pytest.fixture
    def context(self) -> FailureContext:
        """Create a failure context."""
        return FailureContext(
            session_id="test_session",
            message_type="MARKET_DATA",
            direction="outbound",
        )

    @pytest.mark.asyncio
    async def test_disabled_strategy(self, context: FailureContext) -> None:
        """Test that disabled strategy passes messages through."""
        strategy = SilentConnectionStrategy(enabled=False)
        result = await strategy.apply("test message", context)
        assert result == "test message"
        assert strategy.message_count == 1
        assert strategy.dropped_count == 0

    @pytest.mark.asyncio
    async def test_immediate_silence(self, context: FailureContext) -> None:
        """Test that strategy immediately stops sending when enabled."""
        strategy = SilentConnectionStrategy(enabled=True, after_messages=0)

        result1 = await strategy.apply("message1", context)
        assert result1 is None
        assert strategy.message_count == 1
        assert strategy.dropped_count == 1

        result2 = await strategy.apply("message2", context)
        assert result2 is None
        assert strategy.message_count == 2
        assert strategy.dropped_count == 2

    @pytest.mark.asyncio
    async def test_after_messages(self, context: FailureContext) -> None:
        """Test that strategy sends N messages before going silent."""
        strategy = SilentConnectionStrategy(enabled=True, after_messages=3)

        result1 = await strategy.apply("message1", context)
        assert result1 == "message1"
        assert strategy.message_count == 1
        assert strategy.dropped_count == 0

        result2 = await strategy.apply("message2", context)
        assert result2 == "message2"
        assert strategy.message_count == 2
        assert strategy.dropped_count == 0

        result3 = await strategy.apply("message3", context)
        assert result3 == "message3"
        assert strategy.message_count == 3
        assert strategy.dropped_count == 0

        result4 = await strategy.apply("message4", context)
        assert result4 is None
        assert strategy.message_count == 4
        assert strategy.dropped_count == 1

    @pytest.mark.asyncio
    async def test_reset(self, context: FailureContext) -> None:
        """Test reset functionality."""
        strategy = SilentConnectionStrategy(enabled=True, after_messages=2)

        await strategy.apply("msg1", context)
        await strategy.apply("msg2", context)
        await strategy.apply("msg3", context)

        assert strategy.message_count == 3
        assert strategy.dropped_count == 1

        strategy.reset()

        assert strategy.message_count == 0
        assert strategy.dropped_count == 0

        result = await strategy.apply("msg1", context)
        assert result == "msg1"
        assert strategy.message_count == 1

    def test_get_stats(self, context: FailureContext) -> None:
        """Test statistics retrieval."""
        strategy = SilentConnectionStrategy(enabled=True, after_messages=1)
        stats = strategy.get_stats()

        assert stats["enabled"] is True
        assert stats["message_count"] == 0
        assert stats["dropped_count"] == 0

    @pytest.mark.asyncio
    async def test_session_isolation(self, context: FailureContext) -> None:
        """Ensure silence is enforced per session."""
        strategy = SilentConnectionStrategy(enabled=True, after_messages=1)

        ctx1 = context
        ctx2 = FailureContext(
            session_id="other_session",
            message_type="MARKET_DATA",
            direction="outbound",
        )

        assert await strategy.apply("msg1", ctx1) == "msg1"
        assert await strategy.apply("msg2", ctx1) is None

        # New session should still get its first message delivered
        assert await strategy.apply("msg1", ctx2) == "msg1"

