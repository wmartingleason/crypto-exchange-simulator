"""Tests for failure injector."""

import pytest
from unittest.mock import AsyncMock

from src.exchange_simulator.failure_injector import FailureInjector
from src.exchange_simulator.failures.strategies import (
    FailureStrategy,
    FailureContext,
    DropMessageStrategy,
    DelayMessageStrategy,
)


class TestFailureInjector:
    """Test cases for FailureInjector."""

    @pytest.fixture
    def injector(self) -> FailureInjector:
        """Create a failure injector for testing."""
        return FailureInjector()

    @pytest.fixture
    def drop_strategy(self) -> DropMessageStrategy:
        """Create a drop strategy for testing."""
        return DropMessageStrategy(probability=0.5)

    @pytest.fixture
    def delay_strategy(self) -> DelayMessageStrategy:
        """Create a delay strategy for testing."""
        return DelayMessageStrategy(min_ms=10, max_ms=20)

    def test_initial_state(self, injector: FailureInjector) -> None:
        """Test initial state of injector."""
        assert injector.is_enabled()
        assert injector.get_inbound_strategy_count() == 0
        assert injector.get_outbound_strategy_count() == 0

    def test_add_inbound_strategy(
        self, injector: FailureInjector, drop_strategy: DropMessageStrategy
    ) -> None:
        """Test adding inbound strategy."""
        injector.add_inbound_strategy(drop_strategy)
        assert injector.get_inbound_strategy_count() == 1

    def test_add_outbound_strategy(
        self, injector: FailureInjector, drop_strategy: DropMessageStrategy
    ) -> None:
        """Test adding outbound strategy."""
        injector.add_outbound_strategy(drop_strategy)
        assert injector.get_outbound_strategy_count() == 1

    def test_add_multiple_strategies(
        self,
        injector: FailureInjector,
        drop_strategy: DropMessageStrategy,
        delay_strategy: DelayMessageStrategy,
    ) -> None:
        """Test adding multiple strategies."""
        injector.add_inbound_strategy(drop_strategy)
        injector.add_inbound_strategy(delay_strategy)
        assert injector.get_inbound_strategy_count() == 2

    def test_remove_inbound_strategy(
        self, injector: FailureInjector, drop_strategy: DropMessageStrategy
    ) -> None:
        """Test removing inbound strategy."""
        injector.add_inbound_strategy(drop_strategy)
        assert injector.get_inbound_strategy_count() == 1

        result = injector.remove_inbound_strategy(drop_strategy)
        assert result is True
        assert injector.get_inbound_strategy_count() == 0

    def test_remove_nonexistent_strategy(self, injector: FailureInjector) -> None:
        """Test removing a strategy that doesn't exist."""
        strategy = DropMessageStrategy(probability=0.5)
        result = injector.remove_inbound_strategy(strategy)
        assert result is False

    def test_clear_strategies(
        self,
        injector: FailureInjector,
        drop_strategy: DropMessageStrategy,
        delay_strategy: DelayMessageStrategy,
    ) -> None:
        """Test clearing all strategies."""
        injector.add_inbound_strategy(drop_strategy)
        injector.add_outbound_strategy(delay_strategy)

        injector.clear_strategies()

        assert injector.get_inbound_strategy_count() == 0
        assert injector.get_outbound_strategy_count() == 0

    async def test_reset_strategies(self, injector: FailureInjector) -> None:
        """Test resetting all strategies."""
        drop_strategy = DropMessageStrategy(probability=1.0)
        injector.add_inbound_strategy(drop_strategy)

        # Generate some stats
        await injector.inject_inbound("test", "SESSION1")

        injector.reset_strategies()
        assert drop_strategy.get_stats()["dropped_count"] == 0

    def test_enable_disable(self, injector: FailureInjector) -> None:
        """Test enabling and disabling failure injection."""
        assert injector.is_enabled()

        injector.disable()
        assert not injector.is_enabled()

        injector.enable()
        assert injector.is_enabled()

    async def test_inject_inbound_no_strategies(self, injector: FailureInjector) -> None:
        """Test inbound injection with no strategies."""
        result = await injector.inject_inbound("test message", "SESSION1")
        assert result == "test message"

    async def test_inject_inbound_with_strategy(self, injector: FailureInjector) -> None:
        """Test inbound injection with strategy."""
        # Strategy that always passes messages through
        strategy = DropMessageStrategy(probability=0.0)
        injector.add_inbound_strategy(strategy)

        result = await injector.inject_inbound("test message", "SESSION1")
        assert result == "test message"

    async def test_inject_inbound_message_dropped(self, injector: FailureInjector) -> None:
        """Test inbound injection where message is dropped."""
        strategy = DropMessageStrategy(probability=1.0)
        injector.add_inbound_strategy(strategy)

        result = await injector.inject_inbound("test message", "SESSION1")
        assert result is None

    async def test_inject_outbound_no_strategies(self, injector: FailureInjector) -> None:
        """Test outbound injection with no strategies."""
        result = await injector.inject_outbound("test message", "SESSION1")
        assert result == "test message"

    async def test_inject_outbound_with_strategy(self, injector: FailureInjector) -> None:
        """Test outbound injection with strategy."""
        strategy = DropMessageStrategy(probability=0.0)
        injector.add_outbound_strategy(strategy)

        result = await injector.inject_outbound("test message", "SESSION1")
        assert result == "test message"

    async def test_inject_when_disabled(self, injector: FailureInjector) -> None:
        """Test injection when disabled."""
        strategy = DropMessageStrategy(probability=1.0)
        injector.add_inbound_strategy(strategy)
        injector.disable()

        result = await injector.inject_inbound("test message", "SESSION1")
        assert result == "test message"  # Should pass through

    async def test_inject_with_metadata(self, injector: FailureInjector) -> None:
        """Test injection with metadata."""
        strategy = DropMessageStrategy(probability=0.0)
        injector.add_inbound_strategy(strategy)

        metadata = {"key": "value"}
        result = await injector.inject_inbound(
            "test message", "SESSION1", message_type="PLACE_ORDER", metadata=metadata
        )
        assert result == "test message"

    async def test_multiple_strategies_chain(self, injector: FailureInjector) -> None:
        """Test that strategies are applied in sequence."""
        # Both strategies pass messages through
        strategy1 = DropMessageStrategy(probability=0.0)
        strategy2 = DelayMessageStrategy(min_ms=1, max_ms=2)

        injector.add_inbound_strategy(strategy1)
        injector.add_inbound_strategy(strategy2)

        result = await injector.inject_inbound("test message", "SESSION1")
        assert result == "test message"

        # Both strategies should have been applied
        stats = injector.get_statistics()
        assert "inbound" in stats
        assert len(stats["inbound"]) == 2

    async def test_strategy_chain_with_drop(self, injector: FailureInjector) -> None:
        """Test that if one strategy drops, subsequent ones aren't called."""
        drop_strategy = DropMessageStrategy(probability=1.0)
        delay_strategy = DelayMessageStrategy(min_ms=100, max_ms=200)

        injector.add_inbound_strategy(drop_strategy)
        injector.add_inbound_strategy(delay_strategy)

        result = await injector.inject_inbound("test message", "SESSION1")
        assert result is None

        # Delay strategy should not have been called
        stats = injector.get_statistics()
        assert stats["inbound"]["DelayMessageStrategy_1"]["delayed_count"] == 0

    def test_get_statistics(self, injector: FailureInjector) -> None:
        """Test getting statistics."""
        strategy1 = DropMessageStrategy(probability=0.5)
        strategy2 = DelayMessageStrategy(min_ms=10, max_ms=20)

        injector.add_inbound_strategy(strategy1)
        injector.add_outbound_strategy(strategy2)

        stats = injector.get_statistics()

        assert stats["enabled"] is True
        assert "inbound" in stats
        assert "outbound" in stats
        assert "DropMessageStrategy_0" in stats["inbound"]
        assert "DelayMessageStrategy_0" in stats["outbound"]

    def test_get_statistics_empty(self, injector: FailureInjector) -> None:
        """Test getting statistics with no strategies."""
        stats = injector.get_statistics()

        assert stats["enabled"] is True
        assert stats["inbound"] == {}
        assert stats["outbound"] == {}
