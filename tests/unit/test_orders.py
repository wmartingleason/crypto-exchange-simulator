"""Tests for order models."""

import pytest
from decimal import Decimal
from datetime import datetime

from src.exchange_simulator.models.orders import (
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    TimeInForce,
    Fill,
    Position,
)


class TestOrder:
    """Test cases for Order model."""

    def test_create_limit_order(self) -> None:
        """Test creating a limit order."""
        order = Order(
            order_id="ORDER1",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.5"),
        )

        assert order.order_id == "ORDER1"
        assert order.symbol == "BTC/USD"
        assert order.side == OrderSide.BUY
        assert order.price == Decimal("50000")
        assert order.quantity == Decimal("1.5")
        assert order.filled_quantity == Decimal("0")
        assert order.status == OrderStatus.PENDING
        assert order.remaining_quantity == Decimal("1.5")
        assert not order.is_filled

    def test_create_market_order(self) -> None:
        """Test creating a market order."""
        order = Order(
            order_id="ORDER2",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("2.0"),
        )

        assert order.order_type == OrderType.MARKET
        assert order.price is None
        assert order.quantity == Decimal("2.0")

    def test_limit_order_requires_price(self) -> None:
        """Test that limit orders require a price."""
        with pytest.raises(ValueError, match="Price is required for LIMIT orders"):
            Order(
                order_id="ORDER3",
                session_id="SESSION1",
                symbol="BTC/USD",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1.0"),
            )

    def test_price_must_be_positive(self) -> None:
        """Test that price must be positive."""
        with pytest.raises(ValueError, match="Price must be positive"):
            Order(
                order_id="ORDER4",
                session_id="SESSION1",
                symbol="BTC/USD",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("-100"),
                quantity=Decimal("1.0"),
            )

    def test_quantity_must_be_positive(self) -> None:
        """Test that quantity must be positive."""
        with pytest.raises(ValueError):
            Order(
                order_id="ORDER5",
                session_id="SESSION1",
                symbol="BTC/USD",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0"),
            )

    def test_partial_fill(self) -> None:
        """Test partial order fill."""
        order = Order(
            order_id="ORDER6",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("2.0"),
        )

        order.fill(Decimal("0.5"))

        assert order.filled_quantity == Decimal("0.5")
        assert order.remaining_quantity == Decimal("1.5")
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert not order.is_filled

    def test_complete_fill(self) -> None:
        """Test complete order fill."""
        order = Order(
            order_id="ORDER7",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0"),
        )

        order.fill(Decimal("1.0"))

        assert order.filled_quantity == Decimal("1.0")
        assert order.remaining_quantity == Decimal("0")
        assert order.status == OrderStatus.FILLED
        assert order.is_filled

    def test_multiple_fills(self) -> None:
        """Test multiple partial fills."""
        order = Order(
            order_id="ORDER8",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("3.0"),
        )

        order.fill(Decimal("1.0"))
        assert order.status == OrderStatus.PARTIALLY_FILLED

        order.fill(Decimal("1.0"))
        assert order.status == OrderStatus.PARTIALLY_FILLED

        order.fill(Decimal("1.0"))
        assert order.status == OrderStatus.FILLED
        assert order.is_filled

    def test_fill_exceeds_remaining(self) -> None:
        """Test that fill cannot exceed remaining quantity."""
        order = Order(
            order_id="ORDER9",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0"),
        )

        with pytest.raises(ValueError, match="Fill quantity exceeds remaining quantity"):
            order.fill(Decimal("2.0"))

    def test_fill_must_be_positive(self) -> None:
        """Test that fill quantity must be positive."""
        order = Order(
            order_id="ORDER10",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0"),
        )

        with pytest.raises(ValueError, match="Fill quantity must be positive"):
            order.fill(Decimal("0"))

    def test_cancel_order(self) -> None:
        """Test order cancellation."""
        order = Order(
            order_id="ORDER11",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0"),
        )

        order.cancel()
        assert order.status == OrderStatus.CANCELLED

    def test_cannot_cancel_filled_order(self) -> None:
        """Test that filled orders cannot be cancelled."""
        order = Order(
            order_id="ORDER12",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0"),
        )

        order.fill(Decimal("1.0"))

        with pytest.raises(ValueError, match="Cannot cancel order"):
            order.cancel()

    def test_reject_order(self) -> None:
        """Test order rejection."""
        order = Order(
            order_id="ORDER13",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.0"),
        )

        order.reject()
        assert order.status == OrderStatus.REJECTED


class TestFill:
    """Test cases for Fill model."""

    def test_create_fill(self) -> None:
        """Test creating a fill."""
        fill = Fill(
            fill_id="FILL1",
            order_id="ORDER1",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("1.5"),
            is_maker=True,
        )

        assert fill.fill_id == "FILL1"
        assert fill.order_id == "ORDER1"
        assert fill.price == Decimal("50000")
        assert fill.quantity == Decimal("1.5")
        assert fill.is_maker is True


class TestPosition:
    """Test cases for Position model."""

    def test_create_position(self) -> None:
        """Test creating a position."""
        position = Position(symbol="BTC/USD")

        assert position.symbol == "BTC/USD"
        assert position.quantity == Decimal("0")
        assert position.average_price == Decimal("0")
        assert position.realized_pnl == Decimal("0")
        assert position.unrealized_pnl == Decimal("0")

    def test_open_long_position(self) -> None:
        """Test opening a long position."""
        position = Position(symbol="BTC/USD")
        fill = Fill(
            fill_id="FILL1",
            order_id="ORDER1",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("2.0"),
        )

        position.update_on_fill(fill)

        assert position.quantity == Decimal("2.0")
        assert position.average_price == Decimal("50000")
        assert position.realized_pnl == Decimal("0")

    def test_add_to_long_position(self) -> None:
        """Test adding to a long position."""
        position = Position(symbol="BTC/USD", quantity=Decimal("1.0"), average_price=Decimal("50000"))
        fill = Fill(
            fill_id="FILL2",
            order_id="ORDER2",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            price=Decimal("51000"),
            quantity=Decimal("1.0"),
        )

        position.update_on_fill(fill)

        assert position.quantity == Decimal("2.0")
        assert position.average_price == Decimal("50500")  # (50000 + 51000) / 2

    def test_reduce_long_position(self) -> None:
        """Test reducing a long position."""
        position = Position(symbol="BTC/USD", quantity=Decimal("2.0"), average_price=Decimal("50000"))
        fill = Fill(
            fill_id="FILL3",
            order_id="ORDER3",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.SELL,
            price=Decimal("51000"),
            quantity=Decimal("1.0"),
        )

        position.update_on_fill(fill)

        assert position.quantity == Decimal("1.0")
        assert position.average_price == Decimal("50000")  # Average price unchanged
        assert position.realized_pnl == Decimal("1000")  # 1.0 * (51000 - 50000)

    def test_close_position(self) -> None:
        """Test closing a position completely."""
        position = Position(symbol="BTC/USD", quantity=Decimal("1.0"), average_price=Decimal("50000"))
        fill = Fill(
            fill_id="FILL4",
            order_id="ORDER4",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.SELL,
            price=Decimal("52000"),
            quantity=Decimal("1.0"),
        )

        position.update_on_fill(fill)

        assert position.quantity == Decimal("0")
        assert position.realized_pnl == Decimal("2000")  # 1.0 * (52000 - 50000)

    def test_flip_position(self) -> None:
        """Test flipping from long to short."""
        position = Position(symbol="BTC/USD", quantity=Decimal("1.0"), average_price=Decimal("50000"))
        fill = Fill(
            fill_id="FILL5",
            order_id="ORDER5",
            session_id="SESSION1",
            symbol="BTC/USD",
            side=OrderSide.SELL,
            price=Decimal("51000"),
            quantity=Decimal("2.0"),
        )

        position.update_on_fill(fill)

        assert position.quantity == Decimal("-1.0")
        assert position.average_price == Decimal("51000")  # New position average
        assert position.realized_pnl == Decimal("1000")  # Closing 1.0 long at profit

    def test_calculate_unrealized_pnl(self) -> None:
        """Test unrealized PnL calculation."""
        position = Position(symbol="BTC/USD", quantity=Decimal("2.0"), average_price=Decimal("50000"))

        pnl = position.calculate_unrealized_pnl(Decimal("51000"))

        assert pnl == Decimal("2000")  # 2.0 * (51000 - 50000)
        assert position.unrealized_pnl == Decimal("2000")

    def test_short_position_unrealized_pnl(self) -> None:
        """Test unrealized PnL for short position."""
        position = Position(symbol="BTC/USD", quantity=Decimal("-1.0"), average_price=Decimal("50000"))

        pnl = position.calculate_unrealized_pnl(Decimal("49000"))

        assert pnl == Decimal("1000")  # -1.0 * (49000 - 50000) = 1000
