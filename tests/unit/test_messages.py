"""Tests for message models."""

import pytest
from decimal import Decimal
from datetime import datetime

from src.exchange_simulator.models.messages import (
    MessageType,
    Channel,
    PlaceOrderMessage,
    CancelOrderMessage,
    GetOrderMessage,
    GetOrdersMessage,
    SubscribeMessage,
    UnsubscribeMessage,
    PingMessage,
    PongMessage,
    OrderAckMessage,
    OrderFillMessage,
    OrderCancelMessage,
    OrderRejectMessage,
    MarketDataMessage,
    OrderBookUpdateMessage,
    OrderBookLevel,
    TradeMessage,
    ErrorMessage,
)
from src.exchange_simulator.models.orders import OrderSide, OrderType, OrderStatus, TimeInForce


class TestClientMessages:
    """Test cases for client->server messages."""

    def test_place_limit_order_message(self) -> None:
        """Test place limit order message."""
        msg = PlaceOrderMessage(
            request_id="REQ1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.5"),
        )

        assert msg.type == MessageType.PLACE_ORDER
        assert msg.request_id == "REQ1"
        assert msg.symbol == "BTC/USD"
        assert msg.side == OrderSide.BUY
        assert msg.order_type == OrderType.LIMIT
        assert msg.price == Decimal("50000")
        assert msg.quantity == Decimal("1.5")
        assert msg.time_in_force == TimeInForce.GTC

    def test_place_market_order_message(self) -> None:
        """Test place market order message."""
        msg = PlaceOrderMessage(
            symbol="BTC/USD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("2.0"),
        )

        assert msg.order_type == OrderType.MARKET
        assert msg.price is None

    def test_cancel_order_message(self) -> None:
        """Test cancel order message."""
        msg = CancelOrderMessage(request_id="REQ2", order_id="ORDER123")

        assert msg.type == MessageType.CANCEL_ORDER
        assert msg.order_id == "ORDER123"

    def test_get_order_message(self) -> None:
        """Test get order message."""
        msg = GetOrderMessage(order_id="ORDER123")

        assert msg.type == MessageType.GET_ORDER
        assert msg.order_id == "ORDER123"

    def test_get_orders_message(self) -> None:
        """Test get orders message."""
        msg = GetOrdersMessage(symbol="BTC/USD", status=OrderStatus.OPEN)

        assert msg.type == MessageType.GET_ORDERS
        assert msg.symbol == "BTC/USD"
        assert msg.status == OrderStatus.OPEN

    def test_subscribe_message(self) -> None:
        """Test subscribe message."""
        msg = SubscribeMessage(channel=Channel.TRADES, symbol="BTC/USD")

        assert msg.type == MessageType.SUBSCRIBE
        assert msg.channel == Channel.TRADES
        assert msg.symbol == "BTC/USD"

    def test_unsubscribe_message(self) -> None:
        """Test unsubscribe message."""
        msg = UnsubscribeMessage(channel=Channel.ORDERBOOK, symbol="ETH/USD")

        assert msg.type == MessageType.UNSUBSCRIBE
        assert msg.channel == Channel.ORDERBOOK
        assert msg.symbol == "ETH/USD"

    def test_ping_message(self) -> None:
        """Test ping message."""
        msg = PingMessage()

        assert msg.type == MessageType.PING
        assert isinstance(msg.timestamp, datetime)


class TestServerMessages:
    """Test cases for server->client messages."""

    def test_order_ack_message(self) -> None:
        """Test order acknowledgment message."""
        msg = OrderAckMessage(
            request_id="REQ1",
            order_id="ORDER123",
            status=OrderStatus.OPEN,
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.5"),
        )

        assert msg.type == MessageType.ORDER_ACK
        assert msg.order_id == "ORDER123"
        assert msg.status == OrderStatus.OPEN
        assert msg.price == Decimal("50000")

    def test_order_fill_message(self) -> None:
        """Test order fill message."""
        msg = OrderFillMessage(
            fill_id="FILL1",
            order_id="ORDER123",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("0.5"),
            filled_quantity=Decimal("0.5"),
            remaining_quantity=Decimal("1.0"),
            status=OrderStatus.PARTIALLY_FILLED,
            is_maker=True,
        )

        assert msg.type == MessageType.ORDER_FILL
        assert msg.fill_id == "FILL1"
        assert msg.quantity == Decimal("0.5")
        assert msg.status == OrderStatus.PARTIALLY_FILLED
        assert msg.is_maker is True

    def test_order_cancel_message(self) -> None:
        """Test order cancel message."""
        msg = OrderCancelMessage(request_id="REQ2", order_id="ORDER123", symbol="BTC/USD")

        assert msg.type == MessageType.ORDER_CANCEL
        assert msg.order_id == "ORDER123"

    def test_order_reject_message(self) -> None:
        """Test order reject message."""
        msg = OrderRejectMessage(
            request_id="REQ1", order_id="ORDER123", reason="Insufficient balance"
        )

        assert msg.type == MessageType.ORDER_REJECT
        assert msg.reason == "Insufficient balance"

    def test_market_data_message(self) -> None:
        """Test market data message."""
        msg = MarketDataMessage(
            symbol="BTC/USD",
            last_price=Decimal("50000"),
            bid=Decimal("49999"),
            ask=Decimal("50001"),
            volume_24h=Decimal("1000"),
            high_24h=Decimal("51000"),
            low_24h=Decimal("49000"),
        )

        assert msg.type == MessageType.MARKET_DATA
        assert msg.symbol == "BTC/USD"
        assert msg.last_price == Decimal("50000")
        assert msg.bid == Decimal("49999")
        assert msg.ask == Decimal("50001")

    def test_orderbook_update_message(self) -> None:
        """Test order book update message."""
        bids = [
            OrderBookLevel(price=Decimal("49999"), quantity=Decimal("10")),
            OrderBookLevel(price=Decimal("49998"), quantity=Decimal("20")),
        ]
        asks = [
            OrderBookLevel(price=Decimal("50001"), quantity=Decimal("15")),
            OrderBookLevel(price=Decimal("50002"), quantity=Decimal("25")),
        ]

        msg = OrderBookUpdateMessage(symbol="BTC/USD", bids=bids, asks=asks, sequence=12345)

        assert msg.type == MessageType.ORDERBOOK_UPDATE
        assert len(msg.bids) == 2
        assert len(msg.asks) == 2
        assert msg.bids[0].price == Decimal("49999")
        assert msg.asks[0].quantity == Decimal("15")
        assert msg.sequence == 12345

    def test_trade_message(self) -> None:
        """Test trade message."""
        msg = TradeMessage(
            trade_id="TRADE1",
            symbol="BTC/USD",
            price=Decimal("50000"),
            quantity=Decimal("1.5"),
            side=OrderSide.BUY,
        )

        assert msg.type == MessageType.TRADE
        assert msg.trade_id == "TRADE1"
        assert msg.price == Decimal("50000")
        assert msg.quantity == Decimal("1.5")

    def test_pong_message(self) -> None:
        """Test pong message."""
        msg = PongMessage(request_id="PING1")

        assert msg.type == MessageType.PONG
        assert msg.request_id == "PING1"

    def test_error_message(self) -> None:
        """Test error message."""
        msg = ErrorMessage(
            request_id="REQ1",
            code="INVALID_ORDER",
            message="Invalid order parameters",
            details={"field": "price", "issue": "must be positive"},
        )

        assert msg.type == MessageType.ERROR
        assert msg.code == "INVALID_ORDER"
        assert msg.message == "Invalid order parameters"
        assert msg.details["field"] == "price"


class TestMessageSerialization:
    """Test message serialization/deserialization."""

    def test_serialize_place_order(self) -> None:
        """Test serializing place order message."""
        msg = PlaceOrderMessage(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.5"),
        )

        data = msg.model_dump()

        assert data["type"] == "PLACE_ORDER"
        assert data["symbol"] == "BTC/USD"

    def test_deserialize_place_order(self) -> None:
        """Test deserializing place order message."""
        data = {
            "type": "PLACE_ORDER",
            "symbol": "BTC/USD",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": "50000",
            "quantity": "1.5",
        }

        msg = PlaceOrderMessage.model_validate(data)

        assert msg.symbol == "BTC/USD"
        assert msg.side == OrderSide.BUY
        assert msg.price == Decimal("50000")

    def test_serialize_with_timestamp(self) -> None:
        """Test that timestamp is included in serialization."""
        msg = PingMessage()
        data = msg.model_dump()

        assert "timestamp" in data
        assert isinstance(data["timestamp"], datetime)
