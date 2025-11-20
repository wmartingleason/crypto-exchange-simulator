"""Heartbeat message handler."""

from typing import Optional

from .base import MessageHandler
from ..models.messages import Message, PingMessage, PongMessage, ErrorMessage


class HeartbeatHandler(MessageHandler):
    """Handler for heartbeat (ping/pong) messages."""

    async def handle(self, message: Message, session_id: str) -> Optional[Message]:
        """Handle heartbeat messages.

        Args:
            message: The message to handle
            session_id: Session ID

        Returns:
            Response message
        """
        if isinstance(message, PingMessage):
            return PongMessage(request_id=message.request_id)
        else:
            return ErrorMessage(
                code="UNKNOWN_MESSAGE",
                message=f"Unknown message type: {type(message)}",
            )
