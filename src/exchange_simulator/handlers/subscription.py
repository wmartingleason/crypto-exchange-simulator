"""Subscription message handler."""

from typing import Optional

from .base import MessageHandler
from ..models.messages import (
    Message,
    SubscribeMessage,
    UnsubscribeMessage,
    ErrorMessage,
)
from ..connection_manager import ConnectionManager


class SubscriptionHandler(MessageHandler):
    """Handler for subscription messages."""

    def __init__(self, connection_manager: ConnectionManager) -> None:
        """Initialize the subscription handler.

        Args:
            connection_manager: Connection manager instance
        """
        self.connection_manager = connection_manager

    async def handle(self, message: Message, session_id: str) -> Optional[Message]:
        """Handle subscription messages.

        Args:
            message: The message to handle
            session_id: Session ID

        Returns:
            Response message
        """
        if isinstance(message, SubscribeMessage):
            return await self._handle_subscribe(message, session_id)
        elif isinstance(message, UnsubscribeMessage):
            return await self._handle_unsubscribe(message, session_id)
        else:
            return ErrorMessage(
                code="UNKNOWN_MESSAGE",
                message=f"Unknown message type: {type(message)}",
            )

    async def _handle_subscribe(self, message: SubscribeMessage, session_id: str) -> Optional[Message]:
        """Handle subscribe message."""
        channel_key = f"{message.channel.value}:{message.symbol}"
        success = await self.connection_manager.add_subscription(session_id, channel_key)

        if not success:
            return ErrorMessage(
                request_id=message.request_id,
                code="SUBSCRIBE_FAILED",
                message="Failed to subscribe",
            )

        return None  # Success, no response needed

    async def _handle_unsubscribe(self, message: UnsubscribeMessage, session_id: str) -> Optional[Message]:
        """Handle unsubscribe message."""
        channel_key = f"{message.channel.value}:{message.symbol}"
        await self.connection_manager.remove_subscription(session_id, channel_key)
        return None  # Success, no response needed
