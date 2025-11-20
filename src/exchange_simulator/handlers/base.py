"""Base message handler."""

from abc import ABC, abstractmethod
from typing import Optional

from ..models.messages import Message


class MessageHandler(ABC):
    """Abstract base class for message handlers."""

    @abstractmethod
    async def handle(self, message: Message, session_id: str) -> Optional[Message]:
        """Handle a message.

        Args:
            message: The message to handle
            session_id: Session ID of the sender

        Returns:
            Optional response message
        """
        pass
