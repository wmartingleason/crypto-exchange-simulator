"""Order message handler."""

from typing import Optional
from decimal import Decimal

from .base import MessageHandler
from ..models.messages import (
    Message,
    PlaceOrderMessage,
    CancelOrderMessage,
    GetOrderMessage,
    GetOrdersMessage,
    OrderAckMessage,
    OrderFillMessage,
    OrderCancelMessage,
    ErrorMessage,
)
from ..models.orders import OrderStatus
from ..engine.exchange import ExchangeEngine


class OrderHandler(MessageHandler):
    """Handler for order-related messages."""

    def __init__(self, exchange_engine: ExchangeEngine) -> None:
        """Initialize the order handler.

        Args:
            exchange_engine: Exchange engine instance
        """
        self.exchange = exchange_engine

    async def handle(self, message: Message, session_id: str) -> Optional[Message]:
        """Handle order messages.

        Args:
            message: The message to handle
            session_id: Session ID

        Returns:
            Response message
        """
        if isinstance(message, PlaceOrderMessage):
            return await self._handle_place_order(message, session_id)
        elif isinstance(message, CancelOrderMessage):
            return await self._handle_cancel_order(message, session_id)
        elif isinstance(message, GetOrderMessage):
            return await self._handle_get_order(message, session_id)
        elif isinstance(message, GetOrdersMessage):
            return await self._handle_get_orders(message, session_id)
        else:
            return ErrorMessage(
                code="UNKNOWN_MESSAGE",
                message=f"Unknown message type: {type(message)}",
            )

    async def _handle_place_order(
        self, message: PlaceOrderMessage, session_id: str
    ) -> Message:
        """Handle place order message."""
        try:
            order, fills = self.exchange.place_order(
                session_id=session_id,
                symbol=message.symbol,
                side=message.side,
                order_type=message.order_type,
                quantity=message.quantity,
                price=message.price,
                time_in_force=message.time_in_force,
            )

            return OrderAckMessage(
                request_id=message.request_id,
                order_id=order.order_id,
                status=order.status,
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                price=order.price,
                quantity=order.quantity,
            )

        except Exception as e:
            return ErrorMessage(
                request_id=message.request_id,
                code="ORDER_FAILED",
                message=str(e),
            )

    async def _handle_cancel_order(
        self, message: CancelOrderMessage, session_id: str
    ) -> Message:
        """Handle cancel order message."""
        try:
            order = self.exchange.cancel_order(session_id, message.order_id)

            if order:
                return OrderCancelMessage(
                    request_id=message.request_id,
                    order_id=order.order_id,
                    symbol=order.symbol,
                )
            else:
                return ErrorMessage(
                    request_id=message.request_id,
                    code="ORDER_NOT_FOUND",
                    message="Order not found",
                )

        except Exception as e:
            return ErrorMessage(
                request_id=message.request_id,
                code="CANCEL_FAILED",
                message=str(e),
            )

    async def _handle_get_order(
        self, message: GetOrderMessage, session_id: str
    ) -> Message:
        """Handle get order message."""
        order = self.exchange.get_order(session_id, message.order_id)

        if order:
            return OrderAckMessage(
                request_id=message.request_id,
                order_id=order.order_id,
                status=order.status,
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                price=order.price,
                quantity=order.quantity,
            )
        else:
            return ErrorMessage(
                request_id=message.request_id,
                code="ORDER_NOT_FOUND",
                message="Order not found",
            )

    async def _handle_get_orders(
        self, message: GetOrdersMessage, session_id: str
    ) -> Message:
        """Handle get orders message."""
        # This would typically return a custom message type with a list of orders
        # For simplicity, returning an error placeholder
        return ErrorMessage(
            request_id=message.request_id,
            code="NOT_IMPLEMENTED",
            message="Get orders not yet fully implemented",
        )
