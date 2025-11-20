"""Tests for exchange engine."""

import pytest
from decimal import Decimal

from src.exchange_simulator.engine.exchange import ExchangeEngine
from src.exchange_simulator.engine.accounts import AccountManager
from src.exchange_simulator.models.orders import OrderSide, OrderType, OrderStatus, TimeInForce


class TestExchangeEngine:
    """Test cases for ExchangeEngine."""

    @pytest.fixture
    def account_manager(self) -> AccountManager:
        """Create an account manager for testing."""
        return AccountManager(default_balance={"USD": Decimal("100000"), "BTC": Decimal("10")})

    @pytest.fixture
    def engine(self, account_manager: AccountManager) -> ExchangeEngine:
        """Create an exchange engine for testing."""
        return ExchangeEngine(symbols=["BTC/USD", "ETH/USD"], account_manager=account_manager)

    def test_place_limit_buy_order(self, engine: ExchangeEngine) -> None:
        """Test placing a limit buy order."""
        order, fills = engine.place_order(
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
        )

        assert order.status == OrderStatus.OPEN
        assert order.symbol == "BTC/USD"
        assert order.quantity == Decimal("1.0")
        assert len(fills) == 0  # No match since book is empty

    def test_matching_orders(self, engine: ExchangeEngine) -> None:
        """Test that orders match correctly."""
        # Place a limit sell order
        sell_order, _ = engine.place_order(
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
        )

        # Place a limit buy order that matches
        buy_order, fills = engine.place_order(
            session_id="SESSION2",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
        )

        assert len(fills) == 1
        assert fills[0].price == Decimal("50000")
        assert fills[0].quantity == Decimal("1.0")
        assert buy_order.is_filled
        assert sell_order.is_filled

    def test_partial_fill(self, engine: ExchangeEngine) -> None:
        """Test partial order fills."""
        # Place a large sell order
        sell_order, _ = engine.place_order(
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("2.0"),
            price=Decimal("50000"),
        )

        # Place a smaller buy order
        buy_order, fills = engine.place_order(
            session_id="SESSION2",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
        )

        assert len(fills) == 1
        assert buy_order.is_filled
        assert sell_order.status == OrderStatus.PARTIALLY_FILLED
        assert sell_order.remaining_quantity == Decimal("1.0")

    def test_cancel_order(self, engine: ExchangeEngine) -> None:
        """Test cancelling an order."""
        order, _ = engine.place_order(
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
        )

        cancelled = engine.cancel_order("SESSION1", order.order_id)

        assert cancelled is not None
        assert cancelled.status == OrderStatus.CANCELLED

    def test_cannot_cancel_other_session_order(self, engine: ExchangeEngine) -> None:
        """Test that a session cannot cancel another session's order."""
        order, _ = engine.place_order(
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
        )

        with pytest.raises(ValueError, match="does not belong to this session"):
            engine.cancel_order("SESSION2", order.order_id)

    def test_get_orders(self, engine: ExchangeEngine) -> None:
        """Test getting orders for a session."""
        engine.place_order(
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
        )

        engine.place_order(
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.5"),
            price=Decimal("51000"),
        )

        orders = engine.get_orders("SESSION1")
        assert len(orders) == 2

    def test_get_orders_filtered_by_status(self, engine: ExchangeEngine) -> None:
        """Test getting orders filtered by status."""
        order1, _ = engine.place_order(
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
        )

        order2, _ = engine.place_order(
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("51000"),
        )

        engine.cancel_order("SESSION1", order1.order_id)

        open_orders = engine.get_orders("SESSION1", status=OrderStatus.OPEN)
        cancelled_orders = engine.get_orders("SESSION1", status=OrderStatus.CANCELLED)

        assert len(open_orders) == 1
        assert len(cancelled_orders) == 1

    def test_ioc_order(self, engine: ExchangeEngine) -> None:
        """Test IOC (Immediate or Cancel) order."""
        # Place IOC order with no match
        order, fills = engine.place_order(
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
            time_in_force=TimeInForce.IOC,
        )

        assert order.status == OrderStatus.CANCELLED
        assert len(fills) == 0

    def test_unknown_symbol(self, engine: ExchangeEngine) -> None:
        """Test placing order for unknown symbol."""
        with pytest.raises(ValueError, match="Unknown symbol"):
            engine.place_order(
                session_id="SESSION1",
                symbol="UNKNOWN/USD",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1.0"),
                price=Decimal("50000"),
            )

    def test_last_price_updated_on_fill(self, engine: ExchangeEngine) -> None:
        """Test that last price is updated on fills."""
        # Place orders that match
        engine.place_order(
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
        )

        engine.place_order(
            session_id="SESSION2",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
        )

        assert engine.get_last_price("BTC/USD") == Decimal("50000")
