"""Tests for message router."""

import pytest
import json
from decimal import Decimal
from unittest.mock import AsyncMock

from src.exchange_simulator.message_router import MessageRouter, MessageHandler
from src.exchange_simulator.models.messages import (
    Message,
    MessageType,
    PlaceOrderMessage,
    PingMessage,
    PongMessage,
    ErrorMessage,
)
from src.exchange_simulator.models.orders import OrderSide, OrderType


class MockHandler(MessageHandler):
    """Mock message handler for testing."""

    def __init__(self) -> None:
        """Initialize mock handler."""
        self._mock_handle = AsyncMock(return_value=PongMessage())

    async def handle(self, message: Message, session_id: str):
        """Handle a message."""
        return await self._mock_handle(message, session_id)


class TestMessageRouter:
    """Test cases for MessageRouter."""

    @pytest.fixture
    def router(self) -> MessageRouter:
        """Create a message router for testing."""
        return MessageRouter()

    @pytest.fixture
    def mock_handler(self) -> MockHandler:
        """Create a mock handler for testing."""
        return MockHandler()

    def test_register_handler(self, router: MessageRouter, mock_handler: MockHandler) -> None:
        """Test registering a handler."""
        router.register_handler(MessageType.PING, mock_handler)

        handler = router.get_handler(MessageType.PING)
        assert handler is mock_handler

    def test_register_multiple_handlers(
        self, router: MessageRouter, mock_handler: MockHandler
    ) -> None:
        """Test registering multiple handlers."""
        handler2 = MockHandler()

        router.register_handler(MessageType.PING, mock_handler)
        router.register_handler(MessageType.PLACE_ORDER, handler2)

        assert router.get_handler(MessageType.PING) is mock_handler
        assert router.get_handler(MessageType.PLACE_ORDER) is handler2

    def test_unregister_handler(self, router: MessageRouter, mock_handler: MockHandler) -> None:
        """Test unregistering a handler."""
        router.register_handler(MessageType.PING, mock_handler)
        router.unregister_handler(MessageType.PING)

        handler = router.get_handler(MessageType.PING)
        assert handler is None

    def test_get_nonexistent_handler(self, router: MessageRouter) -> None:
        """Test getting a handler that doesn't exist."""
        handler = router.get_handler(MessageType.PING)
        assert handler is None

    async def test_parse_ping_message(self, router: MessageRouter) -> None:
        """Test parsing a ping message."""
        raw = '{"type": "PING"}'
        message = await router.parse_message(raw)

        assert isinstance(message, PingMessage)
        assert message.type == MessageType.PING

    async def test_parse_place_order_message(self, router: MessageRouter) -> None:
        """Test parsing a place order message."""
        raw = json.dumps({
            "type": "PLACE_ORDER",
            "symbol": "BTC/USD",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": "50000",
            "quantity": "1.5",
            "request_id": "REQ1"
        })

        message = await router.parse_message(raw)

        assert isinstance(message, PlaceOrderMessage)
        assert message.type == MessageType.PLACE_ORDER
        assert message.symbol == "BTC/USD"
        assert message.side == OrderSide.BUY
        assert message.order_type == OrderType.LIMIT
        assert message.price == Decimal("50000")
        assert message.quantity == Decimal("1.5")
        assert message.request_id == "REQ1"

    async def test_parse_invalid_json(self, router: MessageRouter) -> None:
        """Test parsing invalid JSON."""
        raw = "not json"

        with pytest.raises(ValueError, match="Invalid JSON"):
            await router.parse_message(raw)

    async def test_parse_non_object_json(self, router: MessageRouter) -> None:
        """Test parsing JSON that's not an object."""
        raw = '["array", "not", "object"]'

        with pytest.raises(ValueError, match="Message must be a JSON object"):
            await router.parse_message(raw)

    async def test_parse_missing_type(self, router: MessageRouter) -> None:
        """Test parsing message without type field."""
        raw = '{"data": "value"}'

        with pytest.raises(ValueError, match="Message must have a 'type' field"):
            await router.parse_message(raw)

    async def test_parse_unknown_type(self, router: MessageRouter) -> None:
        """Test parsing message with unknown type."""
        raw = '{"type": "UNKNOWN_TYPE"}'

        with pytest.raises(ValueError, match="Unknown message type"):
            await router.parse_message(raw)

    async def test_parse_invalid_message_format(self, router: MessageRouter) -> None:
        """Test parsing message with invalid format for its type."""
        # PLACE_ORDER requires symbol, side, etc.
        raw = '{"type": "PLACE_ORDER"}'

        with pytest.raises(ValueError, match="Invalid message format"):
            await router.parse_message(raw)

    async def test_route_valid_message(
        self, router: MessageRouter, mock_handler: MockHandler
    ) -> None:
        """Test routing a valid message."""
        router.register_handler(MessageType.PING, mock_handler)
        raw = '{"type": "PING"}'

        response = await router.route(raw, "SESSION1")

        assert isinstance(response, PongMessage)
        mock_handler._mock_handle.assert_called_once()

    async def test_route_invalid_json(self, router: MessageRouter) -> None:
        """Test routing invalid JSON."""
        raw = "not json"

        response = await router.route(raw, "SESSION1")

        assert isinstance(response, ErrorMessage)
        assert response.code == "INVALID_MESSAGE"

    async def test_route_no_handler(self, router: MessageRouter) -> None:
        """Test routing message with no registered handler."""
        raw = '{"type": "PING"}'

        response = await router.route(raw, "SESSION1")

        assert isinstance(response, ErrorMessage)
        assert response.code == "NO_HANDLER"
        assert "PING" in response.message

    async def test_route_handler_error(
        self, router: MessageRouter, mock_handler: MockHandler
    ) -> None:
        """Test routing when handler raises an error."""
        mock_handler._mock_handle.side_effect = Exception("Handler failed")
        router.register_handler(MessageType.PING, mock_handler)
        raw = '{"type": "PING"}'

        response = await router.route(raw, "SESSION1")

        assert isinstance(response, ErrorMessage)
        assert response.code == "HANDLER_ERROR"
        assert "Handler failed" in response.message

    async def test_route_passes_session_id(
        self, router: MessageRouter, mock_handler: MockHandler
    ) -> None:
        """Test that route passes session ID to handler."""
        router.register_handler(MessageType.PING, mock_handler)
        raw = '{"type": "PING"}'

        await router.route(raw, "SESSION123")

        call_args = mock_handler._mock_handle.call_args
        assert call_args[0][1] == "SESSION123"  # Second argument is session_id

    def test_serialize_message(self, router: MessageRouter) -> None:
        """Test serializing a message."""
        message = PingMessage(request_id="REQ1")

        serialized = router.serialize_message(message)
        data = json.loads(serialized)

        assert data["type"] == "PING"
        assert data["request_id"] == "REQ1"
        assert "timestamp" in data

    def test_serialize_complex_message(self, router: MessageRouter) -> None:
        """Test serializing a complex message."""
        message = PlaceOrderMessage(
            request_id="REQ1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("50000"),
            quantity=Decimal("1.5"),
        )

        serialized = router.serialize_message(message)
        data = json.loads(serialized)

        assert data["type"] == "PLACE_ORDER"
        assert data["symbol"] == "BTC/USD"
        assert data["side"] == "BUY"
        assert data["price"] == "50000"

    async def test_round_trip_serialization(self, router: MessageRouter) -> None:
        """Test that message can be serialized and parsed back."""
        original = PingMessage(request_id="REQ1")
        serialized = router.serialize_message(original)
        parsed = await router.parse_message(serialized)

        assert parsed.type == original.type
        assert parsed.request_id == original.request_id
